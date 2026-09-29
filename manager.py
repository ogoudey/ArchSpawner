"""
Core container manager: one thread-safe registry (dict) per container type,
a shared port pool, and docker lifecycle operations (build, run, stop, remove).

At this scale (< 10 instances at a time, two types) a single RLock guarding
plain dicts is simpler and just as correct as anything fancier.
"""
import threading
import time
import uuid
from dataclasses import dataclass, asdict, field
from typing import Dict, Any, Optional, List

import docker
from docker.errors import NotFound

from config import CONTAINER_TYPES, PORT_RANGE_START, PORT_RANGE_END


@dataclass
class Instance:
    id: str                 # our internal instance id (short uuid, used in the API/TUI)
    container_id: str       # docker container id
    type_key: str
    name: str
    port: int
    internal_port: int
    status: str
    started_at: float
    params: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["started_at_human"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.started_at))
        return d


class PortAllocationError(RuntimeError):
    pass


class ContainerManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._client = docker.from_env()
        self._registries: Dict[str, Dict[str, Instance]] = {k: {} for k in CONTAINER_TYPES}
        self._used_ports: set = set()
        self._built_images: set = set()

    # -- port allocation --------------------------------------------------
    def _allocate_port_locked(self) -> int:
        for port in range(PORT_RANGE_START, PORT_RANGE_END + 1):
            if port not in self._used_ports:
                self._used_ports.add(port)
                return port
        raise PortAllocationError("No free ports left in the configured range.")

    def _release_port_locked(self, port: int) -> None:
        self._used_ports.discard(port)

    # -- image build (lazy, cached per process) ----------------------------
    def _ensure_image_locked(self, type_key: str) -> str:
        cfg = CONTAINER_TYPES[type_key]
        if cfg.image_tag in self._built_images:
            return cfg.image_tag
        dockerfile_path = cfg.dockerfile_path()  # raises RuntimeError if env var unset
        context = cfg.build_context()
        self._client.images.build(
            path=context,
            dockerfile=dockerfile_path,
            tag=cfg.image_tag,
            rm=True,
        )
        self._built_images.add(cfg.image_tag)
        return cfg.image_tag

    # -- spawn --------------------------------------------------------------
    def spawn(self, type_key: str, params: Dict[str, Any]) -> Instance:
        if type_key not in CONTAINER_TYPES:
            raise ValueError(f"Unknown container type: {type_key}")
        cfg = CONTAINER_TYPES[type_key]

        with self._lock:
            image_tag = self._ensure_image_locked(type_key)
            port = self._allocate_port_locked()

        name = params.get("name") or f"{type_key}-{uuid.uuid4().hex[:8]}"
        docker_name = f"spawner-{type_key}-{uuid.uuid4().hex[:8]}"

        env_vars = dict(params.get("env_vars") or {})
        # also surface every scalar param to the container as an env var, so
        # app code inside can see what it was launched with without you having
        # to duplicate that mapping by hand
        for k, v in params.items():
            if k in ("env_vars", "command") or v is None:
                continue
            env_vars[f"SPAWNER_PARAM_{k.upper()}"] = str(v)

        run_kwargs: Dict[str, Any] = dict(
            image=image_tag,
            name=docker_name,
            detach=True,
            ports={f"{cfg.internal_port}/tcp": ("0.0.0.0", port)},
            environment=env_vars,
        )
        if params.get("memory_limit"):
            run_kwargs["mem_limit"] = params["memory_limit"]
        if params.get("cpu_limit"):
            run_kwargs["nano_cpus"] = int(float(params["cpu_limit"]) * 1e9)
        if params.get("command"):
            run_kwargs["command"] = params["command"]

        try:
            container = self._client.containers.run(**run_kwargs)
        except Exception:
            with self._lock:
                self._release_port_locked(port)
            raise

        instance = Instance(
            id=uuid.uuid4().hex[:10],
            container_id=container.id,
            type_key=type_key,
            name=name,
            port=port,
            internal_port=cfg.internal_port,
            status="running",
            started_at=time.time(),
            params=params,
        )
        with self._lock:
            self._registries[type_key][instance.id] = instance
        return instance

    # -- status refresh -------------------------------------------------------
    def _refresh_status(self, instance: Instance) -> None:
        try:
            container = self._client.containers.get(instance.container_id)
            instance.status = container.status
        except NotFound:
            instance.status = "gone"

    # -- listing --------------------------------------------------------------
    def list_instances(self, type_key: Optional[str] = None) -> List[Instance]:
        with self._lock:
            if type_key:
                registries = {type_key: self._registries.get(type_key, {})}
            else:
                registries = self._registries
            instances = [inst for reg in registries.values() for inst in reg.values()]
        for inst in instances:
            self._refresh_status(inst)
        return instances

    def get_instance(self, instance_id: str) -> Optional[Instance]:
        with self._lock:
            for reg in self._registries.values():
                if instance_id in reg:
                    return reg[instance_id]
        return None

    # -- kill -------------------------------------------------------------------
    def kill(self, instance_id: str, timeout: int = 5) -> bool:
        with self._lock:
            instance = None
            owning_registry = None
            for reg in self._registries.values():
                if instance_id in reg:
                    instance = reg[instance_id]
                    owning_registry = reg
                    break
            if instance is None:
                return False

        try:
            container = self._client.containers.get(instance.container_id)
            container.stop(timeout=timeout)
            container.remove(force=True)
        except NotFound:
            pass

        with self._lock:
            owning_registry.pop(instance_id, None)
            self._release_port_locked(instance.port)
        return True

    def kill_all(self) -> int:
        with self._lock:
            ids = [inst.id for reg in self._registries.values() for inst in reg.values()]
        count = 0
        for iid in ids:
            if self.kill(iid):
                count += 1
        return count


# module-level singleton used by the API process
manager = ContainerManager()
