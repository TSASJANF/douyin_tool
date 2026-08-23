"""配置读写 API"""

from fastapi import APIRouter, HTTPException

from .. import config_store
from ..schemas import ConfigBody

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config")
def get_config():
    return {"config": config_store.load_config()}


@router.put("/config")
def put_config(body: ConfigBody):
    try:
        # 先序列化校验，再写回
        import json
        json.dumps(body.config, ensure_ascii=False)
        config_store.save_config(body.config)
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"配置无法序列化为JSON: {e}")
    return {"ok": True}
