"""
HTTP API for the container spawner. One POST endpoint per container type
(each with its own required/optional parameter schema), plus generic
listing and kill endpoints.

Runs open on the network (0.0.0.0) as requested. It has NO auth built in --
put it behind a reverse proxy / VPN / auth layer before exposing it beyond
a trusted network.
"""
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import uvicorn

from config import CONTAINER_TYPES, API_HOST, API_PORT
from manager import manager, PortAllocationError

app = FastAPI(title="Container Spawner")


# ---- per-type request schemas ---------------------------------------------
# These intentionally differ, to match "each endpoint takes a different set
# of required/optional params". Adjust field names/types once the real
# Dockerfiles for each type are known.

class Type1SpawnRequest(BaseModel):
    name: str = Field(..., description="Required. Human-readable instance name.")
    env_vars: Dict[str, str] = Field(default_factory=dict)
    memory_limit: Optional[str] = Field(None, description='e.g. "512m"')
    cpu_limit: Optional[float] = Field(None, description="cores, e.g. 0.5")
    command: Optional[str] = None


class Type2SpawnRequest(BaseModel):
    name: str = Field(..., description="Required. Human-readable instance name.")
    dataset_id: str = Field(..., description="Required. Type2-specific identifier.")
    env_vars: Dict[str, str] = Field(default_factory=dict)
    memory_limit: Optional[str] = None
    cpu_limit: Optional[float] = None
    command: Optional[str] = None


def _spawn_response(instance) -> Dict[str, Any]:
    d = instance.as_dict()
    return {
        "id": d["id"],
        "port": d["port"],
        "status": d["status"],
        "name": d["name"],
        "type": d["type_key"],
        "container_id": d["container_id"][:12],
        "started_at": d["started_at_human"],
    }


@app.post("/spawn/type1")
def spawn_type1(req: Type1SpawnRequest):
    try:
        instance = manager.spawn("type1", req.dict())
    except PortAllocationError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return _spawn_response(instance)


@app.post("/spawn/type2")
def spawn_type2(req: Type2SpawnRequest):
    try:
        instance = manager.spawn("type2", req.dict())
    except PortAllocationError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return _spawn_response(instance)


@app.get("/instances")
def list_instances(type: Optional[str] = None):
    if type and type not in CONTAINER_TYPES:
        raise HTTPException(status_code=404, detail=f"Unknown type '{type}'")
    return [i.as_dict() for i in manager.list_instances(type)]


@app.get("/instances/{instance_id}")
def get_instance(instance_id: str):
    inst = manager.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail="Not found")
    return inst.as_dict()


@app.delete("/instances/{instance_id}")
def kill_instance(instance_id: str):
    ok = manager.kill(instance_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    return {"killed": instance_id}


@app.delete("/instances")
def kill_all():
    return {"killed_count": manager.kill_all()}


@app.get("/types")
def list_types():
    return {
        k: {
            "label": cfg.label,
            "required_params": cfg.required_params,
            "optional_params": cfg.optional_params,
            "internal_port": cfg.internal_port,
        }
        for k, cfg in CONTAINER_TYPES.items()
    }


@app.get("/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run("api:app", host=API_HOST, port=API_PORT, reload=False)
