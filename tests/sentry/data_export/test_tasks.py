from __future__ import absolute_import

from sentry.data_export.base import ExportQueryType
from sentry.data_export.models import ExportedData
from sentry.data_export.tasks import assemble_download
from sentry.models import File
from sentry.snuba.discover import InvalidSearchQuery
from sentry.testutils import TestCase, SnubaTestCase
from sentry.testutils.helpers.datetime import iso_format, before_now
from sentry.utils.compat.mock import patch
from sentry.utils.snuba import (
    QueryOutsideRetentionError,
    QueryIllegalTypeOfArgument,
    SnubaError,
    RateLimitExceeded,
    QueryMemoryLimitExceeded,
    QueryTooManySimultaneous,
    UnqualifiedQueryError,
    QueryExecutionError,
    SchemaValidationError,
)


class AssembleDownloadTest(TestCase, SnubaTestCase):
    def setUp(self):
        super(AssembleDownloadTest, self).setUp()
        self.user = self.create_user()
        self.org = self.create_organization()
        self.project = self.create_project()
        self.event = self.store_event(
            data={
                "tags": {"foo": "bar"},
                "fingerprint": ["group-1"],
                "timestamp": iso_format(before_now(minutes=1)),
            },
            project_id=self.project.id,
        )
        self.store_event(
            data={
                "tags": {"foo": "bar2"},
                "fingerprint": ["group-1"],
                "timestamp": iso_format(before_now(minutes=1)),
            },
            project_id=self.project.id,
        )
        self.store_event(
            data={
                "tags": {"foo": "bar2"},
                "fingerprint": ["group-1"],
                "timestamp": iso_format(before_now(minutes=1)),
            },
            project_id=self.project.id,
        )

    def test_task_persistent_name(self):
        assert assemble_download.name == "sentry.data_export.tasks.assemble_download"

    def test_issue_by_tag(self):
        de = ExportedData.objects.create(
            user=self.user,
            organization=self.org,
            query_type=ExportQueryType.ISSUES_BY_TAG,
            query_info={"project": [self.project.id], "group": self.event.group_id, "key": "foo"},
        )
        with self.tasks():
            assemble_download(de.id, batch_size=1)
        de = ExportedData.objects.get(id=de.id)
        assert de.date_finished is not None
        assert de.date_expired is not None
        assert de.file is not None
        assert isinstance(de.file, File)
        assert de.file.headers == {"Content-Type": "text/csv"}
        # Convert raw csv to list of line-strings
        header, raw1, raw2 = de.file.getfile().read().strip().split("\r\n")
        assert header == "value,times_seen,last_seen,first_seen"

        raw1, raw2 = sorted([raw1, raw2])
        assert raw1.startswith("bar,1,")
        assert raw2.startswith("bar2,2,")

    @patch("sentry.data_export.models.ExportedData.email_failure")
    def test_issue_by_tag_missing_project(self, emailer):
        de = ExportedData.objects.create(
            user=self.user,
            organization=self.org,
            query_type=ExportQueryType.ISSUES_BY_TAG,
            query_info={"project": [-1], "group": self.event.group_id, "key": "user"},
        )
        with self.tasks():
            assemble_download(de.id)
        error = emailer.call_args[1]["message"]
        assert error == "Requested project does not exist"

    @patch("sentry.data_export.models.ExportedData.email_failure")
    def test_issue_by_tag_missing_issue(self, emailer):
        de = ExportedData.objects.create(
            user=self.user,
            organization=self.org,
            query_type=ExportQueryType.ISSUES_BY_TAG,
            query_info={"project": [self.project.id], "group": -1, "key": "user"},
        )
        with self.tasks():
            assemble_download(de.id)
        error = emailer.call_args[1]["message"]
        assert error == "Requested issue does not exist"

    @patch("sentry.tagstore.get_tag_key")
    @patch("sentry.utils.snuba.raw_query")
    @patch("sentry.data_export.models.ExportedData.email_failure")
    def test_issues_by_tag_outside_retention(self, emailer, mock_query, mock_get_tag_key):
        """
        When an issues by tag query goes outside the retention range, it returns 0 results.
        This gives us an empty CSV with just the headers.
        """
        de = ExportedData.objects.create(
            user=self.user,
            organization=self.org,
            query_type=ExportQueryType.ISSUES_BY_TAG,
            query_info={"project": [self.project.id], "group": self.event.group_id, "key": "foo"},
        )

        mock_query.side_effect = QueryOutsideRetentionError("test")
        with self.tasks():
            assemble_download(de.id)
        de = ExportedData.objects.get(id=de.id)
        assert de.date_finished is not None
        assert de.date_expired is not None
        assert de.file is not None
        assert isinstance(de.file, File)
        assert de.file.headers == {"Content-Type": "text/csv"}
        # Convert raw csv to list of line-strings
        header = de.file.getfile().read().strip()
        assert header == "value,times_seen,last_seen,first_seen"

    @patch("sentry.data_export.models.ExportedData.email_failure")
    def test_discover(self, emailer):
        de = ExportedData.objects.create(
            user=self.user,
            organization=self.org,
            query_type=ExportQueryType.DISCOVER,
            query_info={"project": [self.project.id], "field": ["title"], "query": ""},
        )
        with self.tasks():
            assemble_download(de.id)
        de = ExportedData.objects.get(id=de.id)
        assert de.date_finished is not None
        assert de.date_expired is not None
        assert de.file is not None
        assert isinstance(de.file, File)
        assert de.file.headers == {"Content-Type": "text/csv"}
        # Convert raw csv to list of line-strings
        header, raw1, raw2, raw3 = de.file.getfile().read().strip().split("\r\n")
        assert header == "title"

        assert raw1.startswith("<unlabeled event>")
        assert raw2.startswith("<unlabeled event>")
        assert raw3.startswith("<unlabeled event>")

    @patch("sentry.snuba.discover.raw_query")
    @patch("sentry.data_export.models.ExportedData.email_failure")
    def test_discover_outside_retention(self, emailer, mock_query):
        """
        When a discover query goes outside the retention range, email the user they should
        use a more recent date range.
        """
        de = ExportedData.objects.create(
            user=self.user,
            organization=self.org,
            query_type=ExportQueryType.DISCOVER,
            query_info={"project": [self.project.id], "field": ["title"], "query": ""},
        )

        mock_query.side_effect = QueryOutsideRetentionError("test")
        with self.tasks():
            assemble_download(de.id)
        error = emailer.call_args[1]["message"]
        assert error == "Invalid date range. Please try a more recent date range."

        # unicode
        mock_query.side_effect = QueryOutsideRetentionError(u"\xfc")
        with self.tasks():
            assemble_download(de.id)
        error = emailer.call_args[1]["message"]
        assert error == "Invalid date range. Please try a more recent date range."

    @patch("sentry.snuba.discover.query")
    @patch("sentry.data_export.models.ExportedData.email_failure")
    def test_discover_invalid_search_query(self, emailer, mock_query):
        de = ExportedData.objects.create(
            user=self.user,
            organization=self.org,
            query_type=ExportQueryType.DISCOVER,
            query_info={"project": [self.project.id], "field": ["title"], "query": ""},
        )

        mock_query.side_effect = InvalidSearchQuery("test")
        with self.tasks():
            assemble_download(de.id)
        error = emailer.call_args[1]["message"]
        assert error == "Invalid query. Please fix the query and try again."

        # unicode
        mock_query.side_effect = InvalidSearchQuery(u"\xfc")
        with self.tasks():
            assemble_download(de.id)
        error = emailer.call_args[1]["message"]
        assert error == "Invalid query. Please fix the query and try again."

    @patch("sentry.snuba.discover.raw_query")
    @patch("sentry.data_export.models.ExportedData.email_failure")
    def test_discover_snuba_error(self, emailer, mock_query):
        de = ExportedData.objects.create(
            user=self.user,
            organization=self.org,
            query_type=ExportQueryType.DISCOVER,
            query_info={"project": [self.project.id], "field": ["title"], "query": ""},
        )

        mock_query.side_effect = QueryIllegalTypeOfArgument("test")
        with self.tasks():
            assemble_download(de.id)
        error = emailer.call_args[1]["message"]
        assert error == "Invalid query. Argument to function is wrong type."

        # unicode
        mock_query.side_effect = QueryIllegalTypeOfArgument(u"\xfc")
        with self.tasks():
            assemble_download(de.id)
        error = emailer.call_args[1]["message"]
        assert error == "Invalid query. Argument to function is wrong type."

        mock_query.side_effect = SnubaError("test")
        with self.tasks():
            assemble_download(de.id)
        error = emailer.call_args[1]["message"]
        assert error == "Internal error. Please try again."

        # unicode
        mock_query.side_effect = SnubaError(u"\xfc")
        with self.tasks():
            assemble_download(de.id)
        error = emailer.call_args[1]["message"]
        assert error == "Internal error. Please try again."

        mock_query.side_effect = RateLimitExceeded("test")
        with self.tasks():
            assemble_download(de.id)
        error = emailer.call_args[1]["message"]
        assert (
            error
            == "Query timeout. Please try again. If the problem persists try a smaller date range or fewer projects."
        )

        mock_query.side_effect = QueryMemoryLimitExceeded("test")
        with self.tasks():
            assemble_download(de.id)
        error = emailer.call_args[1]["message"]
        assert (
            error
            == "Query timeout. Please try again. If the problem persists try a smaller date range or fewer projects."
        )

        mock_query.side_effect = QueryTooManySimultaneous("test")
        with self.tasks():
            assemble_download(de.id)
        error = emailer.call_args[1]["message"]
        assert (
            error
            == "Query timeout. Please try again. If the problem persists try a smaller date range or fewer projects."
        )

        mock_query.side_effect = UnqualifiedQueryError("test")
        with self.tasks():
            assemble_download(de.id)
        error = emailer.call_args[1]["message"]
        assert error == "Internal error. Your query failed to run."

        mock_query.side_effect = QueryExecutionError("test")
        with self.tasks():
            assemble_download(de.id)
        error = emailer.call_args[1]["message"]
        assert error == "Internal error. Your query failed to run."

        mock_query.side_effect = SchemaValidationError("test")
        with self.tasks():
            assemble_download(de.id)
        error = emailer.call_args[1]["message"]
        assert error == "Internal error. Your query failed to run."
