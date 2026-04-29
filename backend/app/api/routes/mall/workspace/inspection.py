"""
/api/mall/workspace/inspection-cases/*

GET  /         我发现的案件
POST /         创建（status='pending' 等财务审批；found_by = linked_employee_id）
GET  /{id}     详情
GET  /scan?barcode=  扫码查商品真伪 / 批次信息（不创建案件，只查）
"""
# TODO(M4c)
