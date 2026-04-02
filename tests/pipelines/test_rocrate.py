"""Test the nf-core pipelines rocrate command"""

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import git
import requests
import rocrate.rocrate
import yaml
from git import Repo

import nf_core.pipelines.create
import nf_core.pipelines.create.create
import nf_core.pipelines.rocrate
import nf_core.utils
from nf_core.pipelines.bump_version import bump_pipeline_version

from ..test_pipelines import TestPipelines


class TestROCrate(TestPipelines):
    """Class for lint tests"""

    @staticmethod
    def _mock_pipelines_response(url: str, *args, **kwargs):
        class MockResponse:
            def __init__(self, payload, status_code=200, response_url=url):
                self.payload = payload
                self.status_code = status_code
                self.url = response_url

            def json(self):
                return self.payload

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise requests.HTTPError(f"HTTP {self.status_code} for {self.url}")

        if url == "https://nf-co.re/pipelines.json":
            return MockResponse(
                {
                    "remote_workflows": [
                        {
                            "full_name": "nf-core/testpipeline",
                            "name": "testpipeline",
                            "topics": ["test", "pipeline"],
                        }
                    ]
                }
            )
        if url == "https://github.com/my-org/pipelines.json":
            return MockResponse(
                {
                    "remote_workflows": [
                        {
                            "full_name": "my-org/testpipeline",
                            "name": "testpipeline",
                            "topics": ["custom", "org"],
                        }
                    ]
                }
            )
        if url == "https://example.org/pipelines/pipelines.json":
            return MockResponse(
                {
                    "remote_workflows": [
                        {
                            "full_name": "my-org/testpipeline",
                            "name": "testpipeline",
                            "topics": ["custom", "org"],
                        }
                    ]
                }
            )
        if url.startswith("https://api.github.com/users/"):
            return MockResponse({"name": "Test McTestFace"})
        if url.startswith("https://pub.orcid.org/v3.0/search/"):
            return MockResponse({"num-found": 0, "result": []})
        raise AssertionError(f"Unexpected URL requested: {url}")

    def setUp(self) -> None:
        super().setUp()
        # add fake metro map
        Path(self.pipeline_dir, "docs", "images", "nf-core-testpipeline_metro_map.png").touch()
        # rebuild the git history with a deterministic test author
        shutil.rmtree(self.pipeline_dir / ".git")
        repo = Repo.init(self.pipeline_dir)
        with repo.config_writer() as config_writer:
            config_writer.set_value("user", "name", "Test McTestFace")
            config_writer.set_value("user", "email", "test@example.com")

        author = git.Actor("Test McTestFace", "test@example.com")
        repo.git.add(A=True)
        repo.index.commit("Initial commit", author=author, committer=author)
        self.rocrate_obj = nf_core.pipelines.rocrate.ROCrate(self.pipeline_dir)

    def tearDown(self):
        """Clean up temporary files and folders"""

        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    def test_rocrate_creation(self):
        """Run the nf-core rocrate command"""

        # Run the command
        self.rocrate_obj
        with patch("nf_core.pipelines.rocrate.requests.get", side_effect=self._mock_pipelines_response):
            assert self.rocrate_obj.create_rocrate(self.pipeline_dir, self.pipeline_dir)

        # Check that the crate was created
        self.assertTrue(Path(self.pipeline_dir, "ro-crate-metadata.json").exists())

        # Check that the entries in the crate are correct
        crate = rocrate.rocrate.ROCrate(self.pipeline_dir)
        entities = crate.get_entities()

        # Check if the correct entities are set:
        for entity in entities:
            entity_json = entity.as_jsonld()
            if entity_json["@id"] == "./":
                self.assertEqual(
                    entity_json.get("name"), f"{self.pipeline_obj.pipeline_prefix}/{self.pipeline_obj.pipeline_name}"
                )
                self.assertEqual(entity_json["mainEntity"], {"@id": "main.nf"})
            elif entity_json["@id"] == "#main.nf":
                self.assertEqual(entity_json["programmingLanguage"], [{"@id": "#nextflow"}])
                self.assertEqual(entity_json["image"], [{"@id": "nf-core-testpipeline_metro_map.png"}])
            # assert there is a metro map
            # elif entity_json["@id"] == "nf-core-testpipeline_metro_map.png": # FIXME waiting for https://github.com/ResearchObject/ro-crate-py/issues/174
            # self.assertEqual(entity_json["@type"], ["File", "ImageObject"])
            # assert that author is set as a person
            elif "name" in entity_json and entity_json["name"] == "Test McTestFace":
                self.assertEqual(entity_json["@type"], "Person")
                # check that it is set as creator of the main entity
                if crate.mainEntity is not None:
                    self.assertEqual(crate.mainEntity["creator"][0].id, entity_json["@id"])

    def test_rocrate_creation_wrong_pipeline_dir(self):
        """Run the nf-core rocrate command with a wrong pipeline directory"""
        # Run the command

        # Check that it raises a UserWarning
        with self.assertRaises(UserWarning):
            nf_core.pipelines.rocrate.ROCrate(self.pipeline_dir / "bad_dir")

        # assert that the crate was not created
        self.assertFalse(Path(self.pipeline_dir / "bad_dir", "ro-crate-metadata.json").exists())

    def test_rocrate_creation_with_wrong_version(self):
        """Run the nf-core rocrate command with a pipeline version"""
        # Run the command

        self.rocrate_obj = nf_core.pipelines.rocrate.ROCrate(self.pipeline_dir, version="1.0.0")

        # Check that the crate was created
        with self.assertRaises(SystemExit):
            assert self.rocrate_obj.create_rocrate(self.pipeline_dir, self.pipeline_dir)

    def test_rocrate_creation_without_git(self):
        """Run the nf-core rocrate command with a pipeline version"""

        self.rocrate_obj = nf_core.pipelines.rocrate.ROCrate(self.pipeline_dir, version="1.0.0")
        # remove git repo
        shutil.rmtree(self.pipeline_dir / ".git")
        # Check that the crate was created
        with self.assertRaises(SystemExit):
            assert self.rocrate_obj.create_rocrate(self.pipeline_dir, self.pipeline_dir)

    def test_rocrate_creation_to_zip(self):
        """Run the nf-core rocrate command with a zip output"""
        assert self.rocrate_obj.create_rocrate(self.pipeline_dir, zip_path=self.pipeline_dir)
        # Check that the crate was created
        self.assertTrue(Path(self.pipeline_dir, "ro-crate.crate.zip").exists())

    def test_rocrate_creation_uses_template_org(self):
        """Use template.org from .nf-core.yml for the RO-Crate publisher metadata"""
        config_path = Path(self.pipeline_dir, ".nf-core.yml")
        with open(config_path) as fh:
            config = yaml.safe_load(fh)
        config["template"]["org"] = "my-org"
        config["template"]["is_nfcore"] = False
        config["template"].pop("org_url", None)
        with open(config_path, "w") as fh:
            yaml.safe_dump(config, fh, sort_keys=False)

        self.rocrate_obj = nf_core.pipelines.rocrate.ROCrate(self.pipeline_dir)
        with patch("nf_core.pipelines.rocrate.requests.get", side_effect=self._mock_pipelines_response):
            assert self.rocrate_obj.create_rocrate(self.pipeline_dir, self.pipeline_dir)

        with open(Path(self.pipeline_dir, "ro-crate-metadata.json")) as fh:
            crate = json.load(fh)
        entities = {entity["@id"]: entity for entity in crate["@graph"]}

        self.assertIn("https://github.com/my-org", entities)
        self.assertEqual(entities["https://github.com/my-org"]["name"], "my-org")

    def test_rocrate_creation_uses_template_org_params(self):
        """Use template.org_full_name and template.org_url from .nf-core.yml for the RO-Crate publisher metadata"""
        config_path = Path(self.pipeline_dir, ".nf-core.yml")
        with open(config_path) as fh:
            config = yaml.safe_load(fh)
        config["template"]["org"] = "nf-core"
        config["template"]["is_nfcore"] = False
        config["template"]["org_full_name"] = "My Organisation"
        config["template"]["org_url"] = "https://example.org/pipelines"
        with open(config_path, "w") as fh:
            yaml.safe_dump(config, fh, sort_keys=False)

        self.rocrate_obj = nf_core.pipelines.rocrate.ROCrate(self.pipeline_dir)
        with patch("nf_core.pipelines.rocrate.requests.get", side_effect=self._mock_pipelines_response):
            assert self.rocrate_obj.create_rocrate(self.pipeline_dir, self.pipeline_dir)

        with open(Path(self.pipeline_dir, "ro-crate-metadata.json")) as fh:
            crate = json.load(fh)
        entities = {entity["@id"]: entity for entity in crate["@graph"]}
        main_entity = next(entity for entity in crate["@graph"] if entity.get("@id") in {"main.nf", "#main.nf"})

        self.assertIn("https://example.org/pipelines", entities)
        self.assertEqual(entities["https://example.org/pipelines"]["name"], "My Organisation")
        self.assertIn("https://example.org/pipelines/testpipeline/dev", main_entity["url"])
        self.assertIn("nf-core", main_entity["keywords"])
        self.assertIn("custom", main_entity["keywords"])

    def test_rocrate_creation_uses_manifest_homepage_for_release_url(self):
        """Use manifest.homePage to build the RO-Crate main entity URL for release revisions."""
        bump_pipeline_version(self.pipeline_obj, "1.1.0")
        self.rocrate_obj = nf_core.pipelines.rocrate.ROCrate(self.pipeline_dir)

        with patch("nf_core.pipelines.rocrate.requests.get", side_effect=self._mock_pipelines_response):
            assert self.rocrate_obj.create_rocrate(self.pipeline_dir, self.pipeline_dir)

        with open(Path(self.pipeline_dir, "ro-crate-metadata.json")) as fh:
            crate = json.load(fh)
        main_entity = next(entity for entity in crate["@graph"] if entity.get("@id") in {"main.nf", "#main.nf"})

        self.assertEqual(
            main_entity["url"],
            ["https://nf-co.re/testpipeline/1.1.0"],
        )

    def test_rocrate_creation_falls_back_to_default_topics_on_request_error(self):
        """Keep RO-Crate generation working when the pipelines index cannot be fetched."""

        def mock_requests_get(url: str, *args, **kwargs):
            if url.endswith("/pipelines.json"):
                raise requests.exceptions.ConnectionError("offline")
            return self._mock_pipelines_response(url, *args, **kwargs)

        with patch(
            "nf_core.pipelines.rocrate.requests.get",
            side_effect=mock_requests_get,
        ):
            assert self.rocrate_obj.create_rocrate(self.pipeline_dir, self.pipeline_dir)

        with open(Path(self.pipeline_dir, "ro-crate-metadata.json")) as fh:
            crate = json.load(fh)
        main_entity = next(entity for entity in crate["@graph"] if entity.get("@id") in {"main.nf", "#main.nf"})

        self.assertEqual(main_entity["keywords"], ["nf-core", "nextflow"])

    def test_rocrate_creation_falls_back_to_default_topics_on_invalid_json(self):
        """Keep RO-Crate generation working when the pipelines index response cannot be parsed."""

        class InvalidJsonResponse:
            url = "https://nf-co.re/pipelines.json"

            def raise_for_status(self):
                return None

            def json(self):
                raise ValueError("invalid json")

        def mock_requests_get(url: str, *args, **kwargs):
            if url.endswith("/pipelines.json"):
                return InvalidJsonResponse()
            return self._mock_pipelines_response(url, *args, **kwargs)

        with patch("nf_core.pipelines.rocrate.requests.get", side_effect=mock_requests_get):
            assert self.rocrate_obj.create_rocrate(self.pipeline_dir, self.pipeline_dir)

        with open(Path(self.pipeline_dir, "ro-crate-metadata.json")) as fh:
            crate = json.load(fh)
        main_entity = next(entity for entity in crate["@graph"] if entity.get("@id") in {"main.nf", "#main.nf"})

        self.assertEqual(main_entity["keywords"], ["nf-core", "nextflow"])

    def test_rocrate_creation_for_fetchngs(self):
        """Run the nf-core rocrate command with nf-core/fetchngs"""
        tmp_dir = Path(tempfile.mkdtemp())
        # git clone  nf-core/fetchngs
        git.Repo.clone_from("https://github.com/nf-core/fetchngs", tmp_dir / "fetchngs")
        # Run the command
        self.rocrate_obj = nf_core.pipelines.rocrate.ROCrate(tmp_dir / "fetchngs", version="1.12.0")
        assert self.rocrate_obj.create_rocrate(tmp_dir / "fetchngs", self.pipeline_dir)

        # Check that Sateesh Peri is mentioned in creator field

        crate = rocrate.rocrate.ROCrate(self.pipeline_dir)
        entities = crate.get_entities()
        for entity in entities:
            entity_json = entity.as_jsonld()
            if entity_json["@id"] == "#main.nf":
                assert "https://orcid.org/0000-0002-9879-9070" in entity_json["creator"]

        # Clean up
        shutil.rmtree(tmp_dir)

    def test_update_rocrate(self):
        """Run the nf-core rocrate command with a zip output"""

        assert self.rocrate_obj.create_rocrate(json_path=self.pipeline_dir, zip_path=self.pipeline_dir)

        # read the crate json file
        with open(Path(self.pipeline_dir, "ro-crate-metadata.json")) as f:
            crate = json.load(f)

        # check the old version
        self.assertEqual(crate["@graph"][2]["version"][0], "1.0.0dev")
        # check creativeWorkStatus is InProgress
        self.assertEqual(crate["@graph"][0]["creativeWorkStatus"], "InProgress")

        # bump version
        bump_pipeline_version(self.pipeline_obj, "1.1.0")

        # Check that the crate was created
        self.assertTrue(Path(self.pipeline_dir, "ro-crate.crate.zip").exists())

        # Check that the crate was updated
        self.assertTrue(Path(self.pipeline_dir, "ro-crate-metadata.json").exists())

        # read the crate json file
        with open(Path(self.pipeline_dir, "ro-crate-metadata.json")) as f:
            crate = json.load(f)

        # check that the version was updated
        self.assertEqual(crate["@graph"][2]["version"][0], "1.1.0")

        # check creativeWorkStatus is Stable
        self.assertEqual(crate["@graph"][0]["creativeWorkStatus"], "Stable")
