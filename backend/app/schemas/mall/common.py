"""
Mall 通用 schemas：分页、兼容 mall4j 字段名的基础响应。

小程序原始响应格式是 `{records: [...], current, pages, total}`；
ERP 现有约定是 `{items: [...], total}`。
mall schemas 统一用 Pydantic alias 导出 records/current/pages 以避免小程序 36 端点模板改动。
"""
# TODO(M1):
# class MallPageResponse(BaseModel, Generic[T]):
#     records: list[T] = Field(serialization_alias="records")
#     current: int = Field(serialization_alias="current")
#     pages: int = Field(serialization_alias="pages")
#     total: int
