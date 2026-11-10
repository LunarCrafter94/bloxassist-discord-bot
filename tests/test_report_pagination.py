import tempfile
import unittest
from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from bloxfruits_helper_credit_bot.database import DatabaseManager
from bloxfruits_helper_credit_bot.settings import DEFAULT_JOIN_CREDITS, DEFAULT_SERVICES


class ReportPaginationTests(unittest.TestCase):
    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.tempDir.name) / "data",
            defaultJoinCredits=DEFAULT_JOIN_CREDITS,
            defaultServices=DEFAULT_SERVICES,
        )
        self.db = self.manager.ForServer(111111111111111111)
        for index in range(7):
            self.db.CreateScamReport(
                reporterUserId=1000 + index,
                reportedUserId=2000 + index,
                details=f"Report details {index}",
                reportType="bug" if index % 2 == 0 else "scam",
            )

    def tearDown(self):
        self.manager.CloseAll()
        self.tempDir.cleanup()

    def testReportPagesDoNotOverlap(self):
        first = self.db.ListScamReports(status="open", limit=3, offset=0)
        second = self.db.ListScamReports(status="open", limit=3, offset=3)
        firstIds = [int(row["report_id"]) for row in first]
        secondIds = [int(row["report_id"]) for row in second]
        self.assertEqual(len(firstIds), 3)
        self.assertEqual(len(secondIds), 3)
        self.assertFalse(set(firstIds).intersection(secondIds))
        self.assertGreater(firstIds[0], secondIds[0])

    def testReportCategoryFilter(self):
        bugs = self.db.ListScamReports(status="open", reportType="bug", limit=25)
        scams = self.db.ListScamReports(status="open", reportType="scam", limit=25)
        self.assertEqual(len(bugs), 4)
        self.assertEqual(len(scams), 3)
        self.assertTrue(all(row["report_type"] == "bug" for row in bugs))
        self.assertTrue(all(row["report_type"] == "scam" for row in scams))

    def testAllCategoriesAndStatusesCanBePagedTogether(self):
        first = self.db.ListScamReports(status="all", reportType="all", limit=5, offset=0)
        second = self.db.ListScamReports(status="all", reportType="all", limit=5, offset=5)
        self.assertEqual(len(first), 5)
        self.assertEqual(len(second), 2)


if __name__ == "__main__":
    unittest.main()
