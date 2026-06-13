from __future__ import annotations

from fastapi import APIRouter, Depends

from calcchain_backend.dependencies import get_catalog_service
from calcchain_backend.schemas.catalog import CatalogResponse, ConnectionRule
from calcchain_backend.services.catalog_service import CatalogService

router = APIRouter()


@router.get("", response_model=CatalogResponse)
def get_catalog(service: CatalogService = Depends(get_catalog_service)) -> CatalogResponse:
    return service.get_catalog()


@router.get("/connection-rules", response_model=list[ConnectionRule])
def get_connection_rules(service: CatalogService = Depends(get_catalog_service)) -> list[ConnectionRule]:
    return service.get_connection_rules()
