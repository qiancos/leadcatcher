"""FastAPI 应用入口：API 路由 + 单服务托管前端构建产物。"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, db, llm, services


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(
    title="线索捕手 LeadCatcher API",
    version="1.0.0",
    description="AI 营销线索归集 Agent · 解析 / 看板 / 去重 / 反馈 / 统计",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def require_token(x_admin_token: str | None = Header(default=None)) -> None:
    """单口令控制台入口（PRD 6.7）。ADMIN_TOKEN 留空时不校验，方便本地演示。"""
    if config.ADMIN_TOKEN and x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="访问口令错误")


def _handle(exc: services.LeadError) -> HTTPException:
    status = 404 if exc.code == "NOT_FOUND" else 400
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


# ------------------------------------------------------------------ 模型

class ParseRequest(BaseModel):
    text: str = Field(..., description="对话原文")
    force: bool = Field(False, description="文本重复时是否强制再录一条")


class LeadUpdate(BaseModel):
    phone: str | None = None
    customer_industry: str | None = None
    demand: str | None = None
    budget_hint: str | None = None
    intent_level: str | None = None
    risk_note: str | None = None
    follow_status: str | None = None
    is_duplicate: bool | None = None


class VerifyRequest(BaseModel):
    result: str = Field(..., description="correct / wrong / unchecked")


class FeedbackRequest(BaseModel):
    lead_id: int
    wrong_fields: list[str]
    correct_values: dict = Field(default_factory=dict)
    error_category: str = "BC-6"
    note: str | None = None


# ------------------------------------------------------------------ 元信息

@app.get("/api/health")
def health():
    return {"status": "ok", "db": str(config.DB_PATH)}


@app.get("/api/config", dependencies=[Depends(require_token)])
def app_config():
    """前端用它决定是否展示"当前为本地规则引擎"的提示条。"""
    return {
        "provider": config.LLM_PROVIDER,
        "model": config.LLM_MODEL if config.LLM_PROVIDER != "mock" else "本地规则引擎",
        "prompt_version": config.PROMPT_VERSION,
        "max_text_len": config.MAX_TEXT_LEN,
        "batch_limit": config.BATCH_LIMIT,
        "dedup_threshold": config.DEDUP_THRESHOLD,
        "needs_token": bool(config.ADMIN_TOKEN),
        "industries": config.INDUSTRIES,
    }


# ------------------------------------------------------------------ 线索

@app.post("/api/leads/parse", dependencies=[Depends(require_token)])
async def parse_lead(payload: ParseRequest):
    with db.get_conn() as conn:
        try:
            return await services.parse_and_store(conn, payload.text, payload.force)
        except services.LeadError as exc:
            raise _handle(exc)


@app.get("/api/leads", dependencies=[Depends(require_token)])
def list_leads(
    intent: str | None = Query(None, description="逗号分隔：高,中,低,无效"),
    follow_status: str | None = Query(None, description="逗号分隔：pending,followed,invalid"),
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    only_dup: bool = False,
    only_failed: bool = False,
    page: int = 1,
    size: int = 20,
):
    intents = [x for x in (intent or "").split(",") if x] or None
    statuses = [x for x in (follow_status or "").split(",") if x] or None
    with db.get_conn() as conn:
        return services.list_leads(
            conn, intents, statuses, q, date_from, date_to,
            only_dup, only_failed, page, size,
        )


@app.get("/api/leads/{lead_id}", dependencies=[Depends(require_token)])
def get_lead(lead_id: int):
    with db.get_conn() as conn:
        try:
            return services.get_lead(conn, lead_id)
        except services.LeadError as exc:
            raise _handle(exc)


@app.patch("/api/leads/{lead_id}", dependencies=[Depends(require_token)])
def update_lead(lead_id: int, payload: LeadUpdate):
    data = payload.model_dump(exclude_unset=True)
    with db.get_conn() as conn:
        try:
            return services.update_lead(conn, lead_id, data)
        except services.LeadError as exc:
            raise _handle(exc)


@app.delete("/api/leads/{lead_id}", dependencies=[Depends(require_token)])
def delete_lead(lead_id: int):
    with db.get_conn() as conn:
        try:
            return services.delete_lead(conn, lead_id)
        except services.LeadError as exc:
            raise _handle(exc)


@app.post("/api/leads/{lead_id}/restore", dependencies=[Depends(require_token)])
def restore_lead(lead_id: int):
    with db.get_conn() as conn:
        try:
            return services.restore_lead(conn, lead_id)
        except services.LeadError as exc:
            raise _handle(exc)


@app.post("/api/leads/{lead_id}/retry", dependencies=[Depends(require_token)])
async def retry_lead(lead_id: int):
    with db.get_conn() as conn:
        try:
            return await services.retry_parse(conn, lead_id)
        except services.LeadError as exc:
            raise _handle(exc)


@app.post("/api/leads/{lead_id}/verify", dependencies=[Depends(require_token)])
def verify_lead(lead_id: int, payload: VerifyRequest):
    with db.get_conn() as conn:
        try:
            return services.verify_lead(conn, lead_id, payload.result)
        except services.LeadError as exc:
            raise _handle(exc)


# ------------------------------------------------------------------ 反馈

@app.post("/api/feedbacks", dependencies=[Depends(require_token)])
def create_feedback(payload: FeedbackRequest):
    with db.get_conn() as conn:
        try:
            return services.create_feedback(conn, payload.model_dump())
        except services.LeadError as exc:
            raise _handle(exc)


@app.get("/api/feedbacks", dependencies=[Depends(require_token)])
def list_feedbacks(status: str | None = None, limit: int = 100):
    with db.get_conn() as conn:
        return {"items": services.list_feedbacks(conn, status, limit)}


@app.patch("/api/feedbacks/{feedback_id}/close", dependencies=[Depends(require_token)])
def close_feedback(feedback_id: int):
    with db.get_conn() as conn:
        try:
            return services.close_feedback(conn, feedback_id)
        except services.LeadError as exc:
            raise _handle(exc)


# ------------------------------------------------------------------ 统计与导出

@app.get("/api/stats", dependencies=[Depends(require_token)])
def get_stats(days: int = 7):
    with db.get_conn() as conn:
        return services.stats(conn, days)


@app.get("/api/export", dependencies=[Depends(require_token)])
def export_leads():
    with db.get_conn() as conn:
        csv_text = services.export_csv(conn)
    return PlainTextResponse(
        csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="leads.csv"'},
    )


# ------------------------------------------------------------------ 静态资源（单服务部署）

if config.STATIC_DIR.exists() and (config.STATIC_DIR / "index.html").exists():
    assets = config.STATIC_DIR / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str, request: Request):
        if full_path.startswith("api"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = config.STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(config.STATIC_DIR / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def dev_hint():
        return {
            "message": "前端未构建。开发模式请访问 http://localhost:5173",
            "build": "cd web && npm run build",
            "docs": "/docs",
        }
