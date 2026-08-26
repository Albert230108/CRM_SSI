from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_admin_user, get_current_user, get_db
from app.models.ai_model_pricing import AiModelPricing
from app.schemas.ai_model_pricing import AiModelPricingListRead, AiModelPricingRead, AiModelPricingUpsert

router = APIRouter(prefix="/ai-model-pricing", tags=["ai-model-pricing"])


@router.get("", response_model=AiModelPricingListRead, dependencies=[Depends(get_current_user)])
def list_model_pricing(db: Session = Depends(get_db)) -> AiModelPricingListRead:
    rows = db.query(AiModelPricing).order_by(AiModelPricing.model.asc()).all()
    return AiModelPricingListRead(items=rows)


@router.put("", response_model=AiModelPricingRead, dependencies=[Depends(get_current_admin_user)])
def upsert_model_pricing(payload: AiModelPricingUpsert, db: Session = Depends(get_db)) -> AiModelPricing:
    model_name = payload.model.strip()
    if not model_name:
        raise HTTPException(status_code=422, detail="Model name is required")

    row = db.query(AiModelPricing).filter(AiModelPricing.model == model_name).first()
    if row is None:
        row = AiModelPricing(model=model_name)
        db.add(row)

    row.input_cost_per_million_tokens = payload.input_cost_per_million_tokens
    row.output_cost_per_million_tokens = payload.output_cost_per_million_tokens
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{pricing_id}", status_code=204, dependencies=[Depends(get_current_admin_user)])
def delete_model_pricing(pricing_id: int, db: Session = Depends(get_db)) -> None:
    row = db.query(AiModelPricing).filter(AiModelPricing.id == pricing_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Pricing row not found")
    db.delete(row)
    db.commit()
