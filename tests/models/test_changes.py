from tests import BaseTestCase

from redash.models import db, Query, Change, ChangeTrackingMixin


def create_object(factory):
    obj = Query(name='Query',
                description='',
                query_text='SELECT 1',
                user=factory.user,
                data_source=factory.data_source,
                org=factory.org)

    db.session.commit()

    return obj


class TestChangesProperty(BaseTestCase):
    def test_returns_initial_state(self):
        obj = create_object(self.factory)

        for change in Change.query.filter(Change.object == obj):
            self.assertIsNone(change.change['previous'])


class TestLogChange(BaseTestCase):
    def test_properly_logs_first_creation(self):
        obj = create_object(self.factory)
        change = Change.last_change(obj)

        self.assertIsNotNone(change)
        self.assertEqual(change.object_version, 1)
        self.assertEqual(obj.user, change.user)

    def test_skips_unnecessary_fields(self):
        obj = create_object(self.factory)
        change = Change.last_change(obj)

        self.assertIsNotNone(change)
        self.assertEqual(change.object_version, 1)
        for field in change.change:
            self.assertIn(field, Query.tracked_columns)

    def test_properly_log_modification(self):
        obj = create_object(self.factory)
        obj.name = 'Query 2'
        obj.description = 'description'
        db.session.flush()

        change = Change.last_change(obj)

        self.assertIsNotNone(change)
        self.assertEqual(change.object_version, 2)
        self.assertEqual(change.object_version, obj.version)
        self.assertIn('name', change.change)
        self.assertIn('description', change.change)

