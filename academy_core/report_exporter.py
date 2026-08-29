from __future__ import annotations

import csv
import io
import json
from typing import Tuple

from .parent_reporting_models import ParentProgressReport


class ParentReportExporter:
    def to_json(self, report: ParentProgressReport) -> str:
        return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)

    def to_csv(self, reports: Tuple[ParentProgressReport, ...]) -> str:
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(
            [
                "report_id",
                "guardian_id",
                "student_id",
                "student_name",
                "period",
                "period_start",
                "period_end",
                "headline",
                "readiness_summary",
                "generated_at",
            ]
        )
        for report in reports:
            writer.writerow(
                [
                    report.report_id,
                    report.guardian_id,
                    report.student_id,
                    report.student_name,
                    report.period.value,
                    report.period_start,
                    report.period_end,
                    report.headline,
                    report.readiness_summary,
                    report.generated_at,
                ]
            )
        return output.getvalue()
