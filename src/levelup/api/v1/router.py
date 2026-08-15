from fastapi import APIRouter

from levelup.api.v1 import admin, campaigns, crm, dashboard, enrichment, pipeline, reports, schools

router = APIRouter(prefix="/api/v1")
router.include_router(schools.router)
router.include_router(pipeline.router)
router.include_router(campaigns.router)
router.include_router(enrichment.router)
router.include_router(dashboard.router)
router.include_router(crm.router)
router.include_router(admin.router)
router.include_router(reports.router)
