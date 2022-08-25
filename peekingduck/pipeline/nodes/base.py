# Copyright 2022 AI Singapore
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Mixin classes for PeekingDuck nodes and models.

1. Put YOLOv6's weights into the same directory as PeekingDuck, I named the directory
`external_weights`;

2. Define `LOCAL_URL` with "file://" as prefix; e.g. "file:///home/user/weights/yolov6.weights"

3. Used `print(self.sha256sum(weights_path).hexdigest())` to get the weight's checksum;
but I soon realized there is a script
in `scripts/converters/compute_weights_checksum.py` to do so.

4. Remember to get the `weights_checksums.json` file from https://storage.googleapis.com/
peekingduck/models/weights_checksums.json
and update it with the latest addition (i.e. YOLOv6n weights checksum); this should also be
placed in the `external_weights` directory.

5. Modify `WeightsDownloaderMixin` accordingly to check if config has local url flag:

    - `is_local_url` checks if the url in weights config is local;
    - `get_base_url_and_request_session` returns the base url and request session
    depending on the local url flag.
    - The output of `get_base_url_and_request_session` is used in `download_to` and
    `get_weights_checksum`.
    - Potential improvements: the outputs of `get_base_url_and_request_session` are duplicated
    in both `download_to` and `get_weights_checksum`; they share the same session;

6. Global Variables: consider having global vars in a global config class.
"""

import hashlib
import operator
import os
import re
import sys
from syslog import LOG_ALERT
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Union, no_type_check, Tuple
from urllib.request import url2pathname

import requests
from tqdm import tqdm


BASE_URL = "https://storage.googleapis.com/peekingduck/models"
BASE_DIR = Path(__file__).resolve().parents[3].absolute()
LOCAL_URL = (BASE_DIR / "external_weights" / "peekingduck" / "models").as_uri()

PEEKINGDUCK_WEIGHTS_SUBDIR = "peekingduck_weights"


class LocalFileAdapter(requests.adapters.BaseAdapter):
    """Protocol Adapter to allow Requests to GET file:// URLs

    @todo: Properly handle non-empty hostname portions.
    """

    @no_type_check
    @staticmethod
    def _chkpath(method, path):
        """Return an HTTP status for the given filesystem path."""
        if method.lower() in ("put", "delete"):
            return 501, "Not Implemented"
        if method.lower() not in ("get", "head"):
            return 405, "Method Not Allowed"
        if os.path.isdir(path):
            return 400, "Path Not A File"
        if not os.path.isfile(path):
            return 404, "File Not Found"
        if not os.access(path, os.R_OK):
            return 403, "Access Denied"
        return 200, "OK"

    @no_type_check
    def send(self, req, **kwargs):  # pylint: disable=unused-argument, arguments-differ
        """Return the file specified by the given request

        @type req: C{PreparedRequest}
        @todo: Should I bother filling `response.headers` and processing
               If-Modified-Since and friends using `os.stat`?
        """
        path = os.path.normcase(os.path.normpath(url2pathname(req.path_url)))
        response = requests.Response()

        response.status_code, response.reason = self._chkpath(req.method, path)
        if response.status_code == 200 and req.method.lower() != "head":
            try:
                response.raw = open(path, "rb")
            except (OSError, IOError) as err:
                response.status_code = 500
                response.reason = str(err)

        if isinstance(req.url, bytes):
            response.url = req.url.decode("utf-8")
        else:
            response.url = req.url

        response.request = req
        response.connection = self

        return response

    def close(self) -> None:
        pass


class ThresholdCheckerMixin:
    """Mixin class providing utility methods for checking validity of config
    values, typically thresholds.
    """

    interval_pattern = re.compile(
        r"^[\[\(]\s*[-+]?(inf|\d*\.?\d+)\s*,\s*[-+]?(inf|\d*\.?\d+)\s*[\]\)]$"
    )

    def check_bounds(self, key: Union[str, List[str]], interval: str) -> None:
        """Checks if the configuration value(s) specified by `key` satisfies
        the specified bounds.

        Args:
            key (Union[str, List[str]]): The specified key or list of keys.
            interval (str): An mathematical interval representing the range of
                valid values. The syntax of the `interval` string is:

                <value> = <number> | "-inf" | "+inf"
                <left_bracket> = "(" | "["
                <right_bracket> = ")" | "]"
                <interval> = <left_bracket> <value> "," <value> <right_bracket>

                See Technotes for more details.

        Raises:
            TypeError: `key` type is not in (List[str], str).
            ValueError: If `interval` does not match the specified format.
            ValueError: If the lower bound is larger than the upper bound.
            ValueError: If the configuration value fails the bounds comparison.

        Technotes:
            The table below shows the comparison done for various interval
            expressions.

            +---------------------+-------------------------------------+
            | interval            | comparison                          |
            +=====================+=====================================+
            | [lower, +inf]       |                                     |
            +---------------------+                                     |
            | [lower, +inf)       | config[key] >= lower                |
            +---------------------+-------------------------------------+
            | (lower, +inf]       |                                     |
            +---------------------+                                     |
            | (lower, +inf)       | config[key] > lower                 |
            +---------------------+-------------------------------------+
            | [-inf, upper]       |                                     |
            +---------------------+                                     |
            | (-inf, upper]       | config[key] <= upper                |
            +---------------------+-------------------------------------+
            | [-inf, upper)       |                                     |
            +---------------------+                                     |
            | (-inf, upper)       | config[key] < upper                 |
            +---------------------+-------------------------------------+
            | [lower, upper]      | lower <= config[key] <= upper       |
            +---------------------+-------------------------------------+
            | (lower, upper]      | lower < config[key] <= upper        |
            +---------------------+-------------------------------------+
            | [lower, upper)      | lower <= config[key] < upper        |
            +---------------------+-------------------------------------+
            | (lower, upper)      | lower < config[key] < upper         |
            +---------------------+-------------------------------------+
        """
        if self.interval_pattern.match(interval) is None:
            raise ValueError("Badly formatted interval")

        left_bracket = interval[0]
        right_bracket = interval[-1]
        lower, upper = [float(value.strip()) for value in interval[1:-1].split(",")]

        if lower > upper:
            raise ValueError("Lower bound cannot be larger than upper bound")

        self._check_within_bounds(key, lower, upper, left_bracket, right_bracket)

    def check_valid_choice(
        self, key: str, choices: Set[Union[int, float, str]]
    ) -> None:
        """Checks that configuration value specified by `key` can be found
        in `choices`.

        Args:
            key (str): The specified key.
            choices (Set[Union[int, float, str]]): The valid choices.

        Raises:
            TypeError: `key` type is not a str.
            ValueError: If the configuration value is not found in `choices`.
        """
        if not isinstance(key, str):
            raise TypeError("`key` must be str")
        if self.config[key] not in choices:
            raise ValueError(f"{key} must be one of {choices}")

    def _check_within_bounds(  # pylint: disable=too-many-arguments
        self,
        key: Union[str, List[str]],
        lower: float,
        upper: float,
        left_bracket: str,
        right_bracket: str,
    ) -> None:
        """Checks that configuration values specified by `key` is within the
        specified bounds between `lower` and `upper`.

        Args:
            key (Union[str, List[str]]): The specified key or list of keys.
            lower (float): The lower bound.
            upper (float): The upper bound.
            left_bracket (str): Either a "(" for an open lower bound or a "["
                for a closed lower bound.
            right_bracket (str): Either a ")" for an open upper bound or a "]"
                for a closed upper bound.

        Raises:
            TypeError: `key` type is not in (List[str], str).
            ValueError: If the configuration value is not between `lower` and
                `upper`.
        """
        method_lower = operator.ge if left_bracket == "[" else operator.gt
        method_upper = operator.le if right_bracket == "]" else operator.lt
        reason = f"between {left_bracket}{lower}, {upper}{right_bracket}"
        self._compare(key, lower, method_lower, reason)
        self._compare(key, upper, method_upper, reason)

    def _compare(
        self,
        key: Union[str, List[str]],
        value: Union[float, int],
        method: Callable,
        reason: str,
    ) -> None:
        """Compares the configuration values specified by `key` with
        `value` using the specified comparison `method`, raises error with
        `reason` if comparison fails.

        Args:
            key (Union[str, List[str]]): The specified key or list of keys.
            value (Union[float, int]): The specified value.
            method (Callable): The method to be used to compare the
                configuration value specified by `key` and `value`.
            reason (str): The failure reason.

        Raises:
            TypeError: `key` type is not in (List[str], str).
            ValueError: If the comparison between `config[key]` and `value`
                fails.
        """
        if isinstance(key, str):
            if isinstance(self.config[key], list):
                if not all(method(val, value) for val in self.config[key]):
                    raise ValueError(f"All elements of {key} must be {reason}")
            elif not method(self.config[key], value):
                raise ValueError(f"{key} must be {reason}")
        elif isinstance(key, list):
            for k in key:
                self._compare(k, value, method, reason)
        else:
            raise TypeError("`key` must be either str or list")


class WeightsDownloaderMixin:
    """Mixin class providing utility methods for downloading model weights."""

    @property
    def is_local_url(self) -> Optional[Any]:
        """Whether the weights are located in a local folder."""
        return self.weights.get("is_local_url")

    def get_base_url_and_request_session(self) -> Tuple[str, requests.Session]:
        """Returns a requests session."""

        if self.is_local_url:
            base_url = LOCAL_URL
            requests_session = requests.session()
            requests_session.mount("file://", LocalFileAdapter())
        else:
            base_url = BASE_URL
            # https://stackoverflow.com/questions/32986228/difference-between-using
            # -requests-get-and-requests-session-get#:~:text=get()%20creates%20a%20new
            # ,as%20headers%20and%20query%20parameters.
            requests_session = requests.session()
        return base_url, requests_session

    @property
    def blob_filename(self) -> str:
        """Name of the selected weights on GCP."""
        return self.weights["blob_file"][self.config["model_type"]]

    @property
    def classes_filename(self) -> Optional[str]:
        """Name of the file containing classes IDs/labels for the selected
        model.
        """
        return self.weights.get("classes_file")

    @property
    def weights(self) -> Dict[str, Any]:
        """Dictionary of `blob_file`, `config_file`, and `model_file` names
        based on the selected `model_format`.
        """
        return self.config["weights"][self.config["model_format"]]

    @property
    def model_filename(self) -> str:
        """Name of the selected weights on local machine."""
        return self.weights["model_file"][self.config["model_type"]]

    @property
    def model_subdir(self) -> str:
        """Model weights sub-directory name based on the selected model
        format.
        """
        return self.weights["model_subdir"]

    def download_weights(self) -> Path:
        """Downloads weights for specified ``blob_file``.

        Returns:
            (Path): Path to the directory where the model's weights are stored.
        """
        model_dir = self._find_paths()
        if self._has_weights(model_dir):
            return model_dir

        self.logger.info("Proceeding to download...")

        model_dir.mkdir(parents=True, exist_ok=True)
        self._download_to(self.blob_filename, model_dir)
        self._extract_file(model_dir)
        if self.classes_filename is not None:
            self._download_to(self.classes_filename, model_dir)

        self.logger.info(f"Weights downloaded to {model_dir}.")

        return model_dir

    def _download_to(self, filename: str, destination_dir: Path) -> None:
        """Downloads publicly shared files from Google Cloud Platform.

        Saves download content in chunks. Chunk size set to large integer as
        weights are usually pretty large.

        Args:
            destination_dir (Path): Destination directory of downloaded file.
        """

        base_url, requests_session = self.get_base_url_and_request_session()

        with open(destination_dir / filename, "wb") as outfile, requests_session.get(
            f"{base_url}/{self.model_subdir}/{self.config['model_format']}/{filename}",
            stream=True,
        ) as response:
            for chunk in tqdm(response.iter_content(chunk_size=32768)):
                if chunk:  # filter out keep-alive new chunks
                    outfile.write(chunk)

    def _extract_file(self, destination_dir: Path) -> None:
        """Extracts the zip file to ``destination_dir``.

        Args:
            destination_dir (Path): Destination directory for extraction.
        """
        zip_path = destination_dir / self.blob_filename
        with zipfile.ZipFile(zip_path, "r") as infile:
            file_list = infile.namelist()
            for file in tqdm(file=sys.stdout, iterable=file_list, total=len(file_list)):
                infile.extract(member=file, path=destination_dir)

        os.remove(zip_path)

    def _find_paths(self) -> Path:
        """Constructs the `peekingduck_weights` directory path and the model
        sub-directory path.

        Returns:
            (Path): /path/to/peekingduck_weights/<model_name> where
              weights for a model are stored.

        Raises:
            FileNotFoundError: When the user-specified `weights_parent_dir`
                does not exist.
            ValueError: When the user-specified `weights_parent_dir` is not an
                absolute path.
        """
        if self.config["weights_parent_dir"] is None:
            weights_parent_dir = self.config["root"].parent
        else:
            weights_parent_dir = Path(self.config["weights_parent_dir"])

            if not weights_parent_dir.exists():
                raise FileNotFoundError(
                    f"weights_parent_dir does not exist: {weights_parent_dir}"
                )
            if not weights_parent_dir.is_absolute():
                raise ValueError(
                    f"weights_parent_dir must be an absolute path: {weights_parent_dir}"
                )

        return (
            weights_parent_dir
            / PEEKINGDUCK_WEIGHTS_SUBDIR
            / self.model_subdir
            / self.config["model_format"]
        )

    def _get_weights_checksum(self) -> str:
        """Returns the checksum of the weights file."""
        # consider do not call base_url and request session twice? attribute/property?
        base_url, requests_session = self.get_base_url_and_request_session()
        with requests_session.get(f"{base_url}/weights_checksums.json") as response:
            checksums = response.json()
        self.logger.debug(f"weights_checksums: {checksums[self.model_subdir]}")
        return checksums[self.model_subdir][self.config["model_format"]][
            str(self.config["model_type"])
        ]

    def _has_weights(self, model_dir: Path) -> bool:
        """Checks if the specified weights file is present in the model
        sub-directory of the PeekingDuck weights directory.

        Args:
            model_dir (Path): /path/to/peekingduck_weights/<model_name> where
                weights for a model are stored.

        Returns:
            (bool): ``True`` if specified weights file in ``model_dir``
            exists and up-to-date/not corrupted, else ``False``.
        """
        weights_path = model_dir / self.model_filename
        if not weights_path.exists():
            self.logger.warning("No weights detected.")
            return False

        if self.sha256sum(weights_path).hexdigest() != self._get_weights_checksum():
            self.logger.warning("Weights file is corrupted/out-of-date.")
            return False
        return True

    @staticmethod
    def sha256sum(path: Path, hash_func: "hashlib._Hash" = None) -> "hashlib._Hash":
        """Hashes the specified file/directory using SHA256. Reads the file in
        chunks to be more memory efficient.

        When a directory path is passed as the argument, sort the folder
        content and hash the content recursively.

        Args:
            path (Path): Path to the file to be hashed.
            hash_func (Optional[hashlib._Hash]): A hash function which uses the
                SHA-256 algorithm.

        Returns:
            (hashlib._Hash): The updated hash function.
        """
        if hash_func is None:
            hash_func = hashlib.sha256()

        if path.is_dir():
            for subpath in sorted(path.iterdir()):
                if subpath.name not in {".DS_Store", "__MACOSX"}:
                    hash_func = WeightsDownloaderMixin.sha256sum(subpath, hash_func)
        else:
            buffer_size = hash_func.block_size * 1024
            with open(path, "rb") as infile:
                for chunk in iter(lambda: infile.read(buffer_size), b""):
                    hash_func.update(chunk)
        return hash_func
