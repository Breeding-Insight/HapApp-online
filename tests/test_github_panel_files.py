from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from hapapp_python.github_panel_files import (
    GitHubContentRef,
    PanelFileResolutionError,
    madc_panel_github_source,
    resolve_madc_panel_files,
    resolve_madc_panel_lut,
)
from hapapp_python.panels import MADCPanel


class FakeGitHubClient:
    def __init__(self) -> None:
        self.downloads: list[Path] = []

    def get_content(self, content_ref: GitHubContentRef) -> Any:
        if content_ref.kind == "blob":
            return {
                "type": "file",
                "name": Path(content_ref.path).name,
                "download_url": f"mock://{content_ref.path}",
            }
        return [
            {"type": "file", "name": "alfalfa_allele_db_v001.fa", "download_url": "mock://db-v001"},
            {"type": "file", "name": "alfalfa_allele_db_v001_matchCnt_lut.txt", "download_url": "mock://lut-v001"},
            {"type": "file", "name": "alfalfa_allele_db_v010.fa", "download_url": "mock://db-v010"},
            {"type": "file", "name": "alfalfa_allele_db_v010_matchCnt_lut.txt", "download_url": "mock://lut-v010"},
            {"type": "file", "name": "alfalfa_allele_db_v011.fa", "download_url": "mock://db-v011"},
            {"type": "file", "name": "alfalfa_allele_db_v010_indelsAdded.fa", "download_url": "mock://indel"},
        ]

    def download_file(self, file_entry: dict[str, Any], destination_dir: Path) -> Path:
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / str(file_entry["name"])
        destination.write_text(str(file_entry["download_url"]), encoding="utf-8")
        self.downloads.append(destination)
        return destination


def _github_panel(**overrides: object) -> MADCPanel:
    values = {
        "panel_id": "alfalfa",
        "label": "Alfalfa",
        "snpid_lut": "https://github.com/example/private-panel/blob/main/data/snpid_lut.csv",
        "allele_db_base": "https://github.com/example/private-panel/tree/main/data/versions",
        "matchcnt_lut_base": "https://github.com/example/private-panel/tree/main/data/versions",
        "allele_db_indel": None,
        "matchcnt_lut_indel": None,
        "dup_tags": None,
        "first_sample_col": 17,
        "design_len": 54,
        "seq_len": 81,
        "cov": 90,
        "iden": 85,
        "code_ver": "v1",
    }
    values.update(overrides)
    return MADCPanel(**values)


class GitHubPanelFileTests(unittest.TestCase):
    def test_reports_github_repository_and_ref_for_submission_provenance(self) -> None:
        self.assertEqual(
            madc_panel_github_source(_github_panel()),
            ("https://github.com/example/private-panel", "main"),
        )

    def test_copies_local_panel_files_to_run_work_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            work_dir = tmp_path / "work"
            snpid_lut = tmp_path / "snpid_lut.csv"
            allele_db = tmp_path / "allele_db.fa"
            matchcnt_lut = tmp_path / "matchcnt_lut.txt"
            for path in [snpid_lut, allele_db, matchcnt_lut]:
                path.write_text("demo", encoding="utf-8")

            resolved = resolve_madc_panel_files(
                _github_panel(
                    snpid_lut=snpid_lut,
                    allele_db_base=allele_db,
                    matchcnt_lut_base=matchcnt_lut,
                    design_len=59,
                    seq_len=59,
                ),
                work_dir,
            )

            expected_dir = work_dir / "panel_files" / "alfalfa"
            self.assertEqual(resolved.snpid_lut, expected_dir / "snpid_lut.csv")
            self.assertEqual(resolved.allele_db_base, expected_dir / "allele_db.fa")
            self.assertEqual(resolved.matchcnt_lut_base, expected_dir / "matchcnt_lut.txt")
            self.assertTrue(resolved.snpid_lut.is_file())
            self.assertTrue(resolved.allele_db_base.is_file())
            self.assertTrue(resolved.matchcnt_lut_base.is_file())

    def test_downloads_github_panel_files_to_run_work_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir) / "run" / "work"
            client = FakeGitHubClient()

            resolved = resolve_madc_panel_files(_github_panel(), work_dir, github_client=client)

            expected_dir = work_dir / "panel_files" / "alfalfa"
            self.assertEqual(resolved.snpid_lut, expected_dir / "snpid_lut.csv")
            self.assertEqual(resolved.allele_db_base, expected_dir / "alfalfa_allele_db_v010.fa")
            self.assertEqual(
                resolved.matchcnt_lut_base,
                expected_dir / "alfalfa_allele_db_v010_matchCnt_lut.txt",
            )
            self.assertTrue(resolved.snpid_lut.is_file())
            self.assertTrue(all(path.is_relative_to(expected_dir) for path in client.downloads))

    def test_resolves_only_github_lut_for_panel_identification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir) / "work"
            client = FakeGitHubClient()

            lut = resolve_madc_panel_lut(_github_panel(), work_dir, github_client=client)

            self.assertEqual(lut, work_dir / "panel_luts" / "alfalfa" / "snpid_lut.csv")
            self.assertEqual(client.downloads, [lut])

    def test_requires_token_when_no_client_is_injected_for_github_panel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(PanelFileResolutionError) as err:
                resolve_madc_panel_files(_github_panel(), Path(tmp_dir) / "work", github_token="")

        self.assertIn("HAPAPP_GITHUB_TOKEN", str(err.exception))

    def test_rejects_mismatched_base_file_url_and_lut_directory_url(self) -> None:
        panel = _github_panel(
            allele_db_base="https://github.com/example/private-panel/blob/main/data/versions/allele_db_v001.fa"
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(PanelFileResolutionError) as err:
                resolve_madc_panel_files(panel, Path(tmp_dir) / "work", github_client=FakeGitHubClient())

        self.assertIn("both point to files or both point to directories", str(err.exception))


if __name__ == "__main__":
    unittest.main()
