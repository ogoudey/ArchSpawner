"""
Configuration for container types.

Each container type is defined by:
  - a Dockerfile path taken from an environment variable (per your note that
    the Dockerfiles themselves will be wired up later via os.environ)
  - a Docker image tag to build/reuse
  - required and optional parameters accepted by its own /spawn endpoint

To add a third type: add an entry to CONTAINER_TYPES below, add a matching
Pydantic request model + endpoint in api.py, and set its Dockerfile env var
before starting the server.
"""
import os
from dataclasses import dataclass, field
from typing import Dict, Any, Tuple


@dataclass(frozen=True)
class ContainerTypeConfig:
    key: str                       # internal key, e.g. "type1"
    label: str                     # human-readable label (used in the TUI)
    dockerfile_env_var: str        # env var name holding the path to the Dockerfile
    build_context_env_var: str     # env var name holding the build context dir (optional)
    image_tag: str                 # docker image tag to build/reuse
    internal_port: int             # port the process inside the container listens on
    required_params: Tuple[str, ...]
    optional_params: Dict[str, Any] = field(default_factory=dict)

    def dockerfile_path(self) -> str:
        path = os.environ.get(self.dockerfile_env_var)
        if not path:
            raise RuntimeError(
                f"Environment variable {self.dockerfile_env_var} is not set. "
                f"It must point to the Dockerfile for container type '{self.key}'."
            )
        return path

    def build_context(self) -> str:
        ctx = os.environ.get(self.build_context_env_var)
        if ctx:
            return ctx
        # default: the directory containing the Dockerfile
        return os.path.dirname(os.path.abspath(self.dockerfile_path()))


# --- The two container types -------------------------------------------
# Examples -- rename fields / params freely once the real Dockerfiles exist.
# Nothing here hardcodes a Dockerfile path; those come from the environment
# variables named below at build time.

CONTAINER_TYPES: Dict[str, ContainerTypeConfig] = {
    "type1": ContainerTypeConfig(
        key="type1",
        label="Type 1",
        dockerfile_env_var="TYPE1_DOCKERFILE",
        build_context_env_var="TYPE1_BUILD_CONTEXT",
        image_tag="spawner/type1:latest",
        internal_port=8000,
        required_params=("name",),
        optional_params={"env_vars": {}, "memory_limit": None, "cpu_limit": None, "command": None},
    ),
    "type2": ContainerTypeConfig(
        key="type2",
        label="Type 2",
        dockerfile_env_var="TYPE2_DOCKERFILE",
        build_context_env_var="TYPE2_BUILD_CONTEXT",
        image_tag="spawner/type2:latest",
        internal_port=8000,
        required_params=("name", "dataset_id"),
        optional_params={"env_vars": {}, "memory_limit": None, "cpu_limit": None, "command": None},
    ),
}

PORT_RANGE_START = int(os.environ.get("SPAWNER_PORT_RANGE_START", "8001"))
PORT_RANGE_END = int(os.environ.get("SPAWNER_PORT_RANGE_END", "8999"))

API_HOST = os.environ.get("SPAWNER_API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("SPAWNER_API_PORT", "9000"))
