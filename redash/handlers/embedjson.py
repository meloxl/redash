import json
import pystache
import time
import logging

from funcy import project
from flask import render_template, request
from flask_login import login_required, current_user
from flask_restful import abort

from redash import models, settings, utils
from redash import serializers
from redash.utils import json_dumps, collect_parameters_from_request, gen_query_hash
from redash.handlers import routes
from redash.handlers.base import org_scoped_rule, record_event
from redash.handlers.query_results import collect_query_parameters
from redash.permissions import require_access, view_only
from authentication import current_org

#
# Run a parameterized query synchronously and return the result
# DISCLAIMER: Temporary solution to support parameters in queries. Should be
#             removed once we refactor the query results API endpoints and handling
#             on the client side. Please don't reuse in other API handlers.
#
def run_query_sync(data_source, parameter_values, query_text, max_age=0):
    query_parameters = set(collect_query_parameters(query_text))
    missing_params = set(query_parameters) - set(parameter_values.keys())
    if missing_params:
        raise Exception('Missing parameter value for: {}'.format(", ".join(missing_params)))

    if query_parameters:
        query_text = pystache.render(query_text, parameter_values)

    if max_age <= 0:
        query_result = None
    else:
        query_result = models.QueryResult.get_latest(data_source, query_text, max_age)

    query_hash = gen_query_hash(query_text)

    if query_result:
        logging.info("Returning cached result for query %s" % query_hash)
        return query_result.data

    try:
        started_at = time.time()
        data, error = data_source.query_runner.run_query(query_text)

        if error:
            return None
        # update cache
        if max_age > 0:
            run_time = time.time() - started_at
            query_result, updated_query_ids = models.QueryResult.store_result(data_source.org_id, data_source.id,
                                                                              query_hash, query_text, data,
                                                                              run_time, utils.utcnow())

        return data
    except Exception, e:
        if max_age > 0:
            abort(404, message="Unable to get result from the database, and no cached query result found.")
        else:
            abort(503, message="Unable to get result from the database.")
        return None


@routes.route(org_scoped_rule('/embedjson/query/<query_id>'), methods=['GET'])
@login_required
def embedjson(query_id, org_slug=None):
    visualizations = 1
    logging.info('entering embedjson 3  ')
    logging.info(+settings.ALLOW_PARAMETERS_IN_EMBEDS)

    query = models.Query.get_by_id_and_org(query_id, current_org)
    require_access(query.groups, current_user, view_only)
    qr = {}

    parameter_values = collect_parameters_from_request(request.args)

    qr = query.latest_query_data
    if settings.ALLOW_PARAMETERS_IN_EMBEDS == True and len(parameter_values) > 0:
        # run parameterized query
        #
        # WARNING: Note that the external query parameters
        #          are a potential risk of SQL injections.
        #
        max_age = int(request.args.get('maxAge', 0))
        results = run_query_sync(query.data_source, parameter_values, query.query, max_age=max_age)
        if results is None:
            abort(400, message="Unable to get results for this query")
        else:
            qr = {"data": json.loads(results)}
    elif qr is None:
        abort(400, message="No Results for this query")
    else:
        qr = qr.to_dict()

    record_event(current_org, current_user, {
        'action': 'view',
        'query_id': query_id,
        'embed': True,
        'referer': request.headers.get('Referer')
    })

    client_config = {}
    client_config.update(settings.COMMON_CLIENT_CONFIG)
    qr = project(qr, ('data', 'id', 'retrieved_at'))
    return json_dumps(qr), 200, {'Content-Type': 'application/json; charset=utf-8'}