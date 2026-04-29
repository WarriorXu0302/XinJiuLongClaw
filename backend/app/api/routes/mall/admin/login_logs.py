"""
/api/mall/admin/login-logs/*

GET /                    全局登录日志（按 user/date/method/ip 过滤）
GET /users/{id}          某用户登录历史
GET /stats               按 user 聚合最近 N 天登录次数（识别频繁查价异常）
"""
# TODO(M5)
