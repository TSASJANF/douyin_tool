"""配置读写 API"""

import json

from fastapi import APIRouter, HTTPException

from .. import config_store
from ..config_validation import ConfigValidationError, validate_config
from ..schemas import ConfigBody

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config")
def get_config():
    return {"config": config_store.load_config()}


@router.put("/config")
def put_config(body: ConfigBody):
    config = body.config
    # 先序列化校验，再写回
    try:
        json.dumps(config, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"配置无法序列化为JSON: {e}")

    # 字段级校验：非法配置直接拒绝写入，并一次告知全部具体原因
    try:
        validate_config(config)
    except ConfigValidationError as e:
        raise HTTPException(status_code=400, detail="配置校验未通过：" + "；".join(e.problems))

    config_store.save_config(config)
    return {"ok": True}
