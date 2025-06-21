import os
import json
import uuid
import hashlib
import logging
import re
from typing import Dict, List, Any, Optional, Union, Tuple
from fastapi import FastAPI, HTTPException, Request, File, UploadFile, Form, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import aiofiles
import asyncio
from pymilvus import Collection, connections, utility, FieldSchema, CollectionSchema, DataType
import numpy as np
import config
from fastapi.middleware.cors import CORSMiddleware
import shutil
import glob
import uvicorn

# 配置日志
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(title="错题文档管理系统")

# 配置静态文件和模板
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure storage directory exists
os.makedirs(config.JSON_STORAGE_PATH, exist_ok=True)

# 定义学科列表及其关键词
SUBJECTS = {
    "math": ["数学", "math", "mathematics", "计算", "公式", "方程", "函数", "几何", "代数", "微积分", "三角", "概率", "统计"],
    "english": ["英语", "english", "单词", "词汇", "语法", "阅读理解", "听力", "写作", "口语", "翻译", "外语"],
    "chinese": ["语文", "chinese", "文言文", "古诗", "阅读", "写作", "作文", "诗词", "散文", "小说", "文学", "汉语"],
    "physics": ["物理", "physics", "力学", "电学", "热学", "光学", "声学", "磁学", "能量", "功率", "速度", "加速度"],
    "chemistry": ["化学", "chemistry", "元素", "分子", "原子", "化合物", "反应", "酸碱", "氧化", "还原"],
    "biology": ["生物", "biology", "生命", "细胞", "基因", "遗传", "进化", "生态", "微生物", "植物", "动物", "人体"],
    "history": ["历史", "history", "朝代", "年代", "事件", "人物", "战争", "革命", "文化", "政治史", "经济史"],
    "geography": ["地理", "geography", "地形", "气候", "资源", "人口", "经济", "文化", "环境", "地图", "地球"],
    "politics": ["政治", "politics", "思想", "制度", "法律", "道德", "社会", "民主", "权利", "义务", "公民"]
}

# Document model
class Document(BaseModel):
    content: Union[Dict[str, Any], List[Any]]  # 允许字典或列表
    keywords: Optional[List[str]] = None  # 保持变量名不变，但实际表示备注
    subject: Optional[str] = None  # 新增学科字段

class SearchQuery(BaseModel):
    keyword: str
    subject: Optional[str] = None  # 新增按学科搜索
    limit: int = 10

# 简化的向量生成函数，实际应用中应使用更复杂的模型
def generate_embedding(text: str) -> List[float]:
    """生成文本的向量嵌入（简化版本）"""
    # 使用简单的哈希函数生成伪向量
    hash_obj = hashlib.md5(text.encode())
    hash_bytes = hash_obj.digest()
    # 将哈希值转换为浮点数向量
    vector = [float(byte / 255.0) for byte in hash_bytes]
    # 确保向量维度为128
    while len(vector) < 128:
        vector.extend(vector[:128 - len(vector)])
    return vector[:128]

# 根据文本内容判断学科类别
def detect_subject(text: str) -> str:
    """
    根据文本内容判断学科类别
    返回学科的英文名称（如math, english等）
    """
    # 将文本转为小写以便匹配
    text_lower = text.lower()
    
    # 计算每个学科的匹配分数
    subject_scores = {}
    for subject, keywords in SUBJECTS.items():
        score = 0
        for keyword in keywords:
            # 计算关键词在文本中出现的次数
            count = text_lower.count(keyword.lower())
            score += count
        subject_scores[subject] = score
    
    # 找出得分最高的学科
    if max(subject_scores.values()) > 0:
        return max(subject_scores.items(), key=lambda x: x[1])[0]
    else:
        # 如果没有匹配到任何学科关键词，返回"other"
        return "other"

# 获取下一个学科特定的文档ID
async def get_next_subject_doc_id(subject: str) -> int:
    """
    获取指定学科的下一个文档ID
    例如：如果已有math_1.json, math_2.json，则返回3
    """
    files = os.listdir(config.JSON_STORAGE_PATH)
    # 筛选出特定学科的文件
    subject_files = [f for f in files if f.startswith(f"{subject}_") and f.endswith('.json')]
    
    if not subject_files:
        return 1
    
    # 提取ID部分并找出最大值
    ids = []
    for file_name in subject_files:
        # 使用正则表达式提取数字部分
        match = re.search(r'_(\d+)\.json$', file_name)
        if match:
            ids.append(int(match.group(1)))
    
    return max(ids) + 1 if ids else 1

# Connect to Milvus and initialize collection
async def init_milvus():
    try:
        # Connect to Milvus server
        connections.connect(
            alias="default", 
            host=config.MILVUS_HOST, 
            port=config.MILVUS_PORT
        )
        logger.info(f"成功连接到Milvus服务器: {config.MILVUS_HOST}:{config.MILVUS_PORT}")
        
        # Check if collection exists, if not create it
        if not utility.has_collection(config.COLLECTION_NAME):
            logger.info(f"创建新的Milvus集合: {config.COLLECTION_NAME}")
            # Define fields for the collection
            fields = [
                FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=100),
                FieldSchema(name="file_path", dtype=DataType.VARCHAR, max_length=500),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=128),  # 使用128维向量
                FieldSchema(name="keywords", dtype=DataType.VARCHAR, max_length=4000),  # 进一步增加最大长度以支持更长的文本
                FieldSchema(name="subject", dtype=DataType.VARCHAR, max_length=50),  # 确保添加学科字段
            ]
            
            # Create collection schema
            schema = CollectionSchema(fields=fields, description="Wrong documents collection")
            
            # Create collection
            collection = Collection(name=config.COLLECTION_NAME, schema=schema)
            
            # 创建索引
            index_params = {
                "metric_type": "L2",
                "index_type": "IVF_FLAT",
                "params": {"nlist": 128}
            }
            collection.create_index(field_name="embedding", index_params=index_params)
            logger.info(f"创建索引成功")
        else:
            # Get existing collection
            logger.info(f"使用现有的Milvus集合: {config.COLLECTION_NAME}")
            collection = Collection(name=config.COLLECTION_NAME)
            
            # 检查现有集合的字段结构
            schema = collection.schema
            field_names = [field.name for field in schema.fields]
            logger.info(f"现有集合字段: {field_names}")
            
            # 如果keywords字段长度不足，提示用户
            if "keywords" in field_names:
                keywords_field = next((f for f in schema.fields if f.name == "keywords"), None)
                if keywords_field and hasattr(keywords_field, 'max_length'):
                    logger.warning(f"警告: 'keywords'字段最大长度为{keywords_field.max_length}，可能导致长文本被截断")
            
            # 如果缺少subject字段，记录警告
            if "subject" not in field_names:
                logger.warning(f"警告: 现有集合缺少'subject'字段，某些功能可能无法正常工作")
        
        # Load collection
        collection.load()
        logger.info(f"Milvus集合加载成功")
        return collection
    except Exception as e:
        logger.error(f"初始化Milvus时出错: {str(e)}")
        raise

# 分析JSON内容，判断学科类别
async def analyze_json_content(content: Union[Dict, List]) -> str:
    """
    分析JSON内容，判断学科类别
    """
    # 将JSON内容转换为字符串
    content_str = json.dumps(content, ensure_ascii=False)
    # 判断学科类别
    return detect_subject(content_str)

# 处理单个JSON文件存储
async def process_json_file(file_path: str, keywords: List[str] = None, subject_override: str = None):
    try:
        logger.info(f"处理JSON文件: {file_path}")
        # 读取JSON文件内容
        async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
            content = await f.read()
            json_content = json.loads(content)
        
        # 如果没有指定学科，自动判断
        subject = subject_override
        if not subject:
            subject = await analyze_json_content(json_content)
            logger.info(f"自动判断学科: {subject}")
        
        # 创建Document对象
        document = Document(content=json_content, keywords=keywords, subject=subject)
        
        # 存储文档
        return await store_document(document)
    except Exception as e:
        logger.error(f"处理JSON文件失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"处理JSON文件失败: {str(e)}")

# 使用lifespan代替on_event (将在后续版本更新)
@app.on_event("startup")
async def startup_event():
    app.state.collection = await init_milvus()
    
    # 检查并记录集合结构
    field_names = [field.name for field in app.state.collection.schema.fields]
    logger.info(f"Milvus集合字段: {field_names}")
    app.state.milvus_fields = field_names

# 主页路由
@app.get("/")
async def home(request: Request):
    """返回主页"""
    return templates.TemplateResponse("index.html", {"request": request})

# Favicon路由
@app.get("/favicon.ico")
async def favicon():
    return FileResponse("static/favicon.ico")

# 获取所有可用学科
@app.get("/subjects/")
async def get_subjects():
    """获取错题目录中的所有科目"""
    try:
        ERROR_BASE_DIR = "/root/error_question"
        subjects = [d for d in os.listdir(ERROR_BASE_DIR) 
                   if os.path.isdir(os.path.join(ERROR_BASE_DIR, d)) and not d.startswith('.')]
        
        logger.info(f"获取到的科目列表: {subjects}")
        
        # 科目名称映射（英文到中文）
        SUBJECT_NAMES = {
            'math': '数学',
            'history': '历史',
            'chinese': '语文',
            'english': '英语',
            'geography': '地理',
            'politics': '政治',
            'chemistry': '化学',
            'biology': '生物',
            'physics': '物理'
        }
        
        # 添加中文名称
        subject_info = []
        for subj in subjects:
            info = {
                "id": subj,
                "name": SUBJECT_NAMES.get(subj, subj)
            }
            subject_info.append(info)
            
        return {"subjects": subject_info}
    except Exception as e:
        logger.error(f"获取科目失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取科目失败: {str(e)}")

# Store document endpoint
@app.post("/documents/", status_code=201)
async def store_document(document: Document):
    try:
        # 如果没有指定学科，自动判断
        if not document.subject:
            document.subject = await analyze_json_content(document.content)
            logger.info(f"自动判断学科: {document.subject}")
        
        # 获取下一个学科特定的文档ID
        doc_id = await get_next_subject_doc_id(document.subject)
        file_name = f"{document.subject}_{doc_id}.json"
        file_path = os.path.join(config.JSON_STORAGE_PATH, file_name)
        
        # Save document to file
        async with aiofiles.open(file_path, 'w') as f:
            await f.write(json.dumps(document.content, ensure_ascii=False, indent=2))
        
        # 准备备注文本
        keywords_text = ""
        if document.keywords:
            keywords_text = ",".join(document.keywords)
        else:
            # 如果没有提供备注，则提取文档内容作为默认备注
            content_str = json.dumps(document.content)
            keywords_text = content_str[:1000]  # 限制长度
        
        # 生成向量嵌入
        embedding = generate_embedding(keywords_text)
        
        # Insert data into Milvus
        collection = app.state.collection
        doc_unique_id = str(uuid.uuid4())
        
        logger.info(f"向Milvus插入文档: ID={doc_id}, UUID={doc_unique_id}, 学科={document.subject}, 文件路径={file_path}")
        
        collection.insert([
            [doc_unique_id],      # id
            [file_path],          # file_path
            [embedding],          # embedding
            [keywords_text],      # 备注文本
            [document.subject],   # 学科
        ])
        
        logger.info(f"文档存储成功: ID={doc_id}, 学科={document.subject}, 文件名={file_name}")
        return {
            "id": doc_id, 
            "subject": document.subject, 
            "file_name": file_name, 
            "message": "Document stored successfully"
        }
    
    except Exception as e:
        logger.error(f"存储文档失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to store document: {str(e)}")

# 上传单个JSON文件
@app.post("/upload/")
async def upload_file(
    file: UploadFile = File(...),
    keywords: str = Form("")
):
    """上传单个JSON文件"""
    try:
        logger.info(f"接收到上传文件请求: {file.filename}")
        # 验证文件类型
        if not file.filename.endswith('.json'):
            raise HTTPException(status_code=400, detail="只接受JSON文件")
        
        # 获取文件名（去除路径）
        original_filename = os.path.basename(file.filename)
        logger.info(f"处理文件: {original_filename}，原始路径: {file.filename}")
        
        # 读取文件内容
        content = await file.read()
        file_content = content.decode('utf-8')
        
        # 验证JSON格式
        try:
            json_data = json.loads(file_content)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="无效的JSON格式")
        
        # 分析文档内容确定学科
        subject = await analyze_json_content(json_data)
        logger.info(f"自动识别文件 {original_filename} 的学科为: {subject}")
        
        # 获取下一个学科特定的文档ID
        doc_id = await get_next_subject_doc_id(subject)
        filename = f"{subject}_{doc_id}.json"
        file_path = os.path.join(config.JSON_STORAGE_PATH, filename)
        
        logger.info(f"保存文件到: {file_path}")
        # 保存文件
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        
        # 提取文本内容用于向量化 - 使用与upload_directory相同的逻辑
        text_content = ""
        if isinstance(json_data, list):
            # 限制处理的条目数量，避免生成过长的文本
            items_to_process = json_data[:5] if len(json_data) > 5 else json_data
            for item in items_to_process:
                if isinstance(item, dict):
                    # 只使用最重要的字段
                    important_fields = ['content', 'question', 'title', 'description']
                    for field in important_fields:
                        if field in item and item[field]:
                            text_content += str(item[field]) + " "
                            break
                    # 如果没有找到重要字段，添加前3个值
                    if not text_content and len(item) > 0:
                        text_content += " ".join(str(v) for v in list(item.values())[:3] if v)
        elif isinstance(json_data, dict):
            # 只使用最重要的字段或前5个值
            important_fields = ['content', 'question', 'title', 'description']
            for field in important_fields:
                if field in json_data and json_data[field]:
                    text_content += str(json_data[field]) + " "
                    break
            # 如果没有找到重要字段，添加前5个值
            if not text_content:
                text_content += " ".join(str(v) for v in list(json_data.values())[:5] if v)
        
        # 生成向量嵌入
        embedding = generate_embedding(text_content)
        
        # 添加到Milvus向量数据库
        try:
            collection = app.state.collection
            doc_unique_id = str(uuid.uuid4())
            
            # 截断过长的文本内容，避免超出Milvus字段长度限制
            keywords_max_length = 1000  # 默认值
            
            # 尝试获取字段的实际长度限制
            try:
                schema = collection.schema
                keywords_field = next((f for f in schema.fields if f.name == "keywords"), None)
                if keywords_field and hasattr(keywords_field, 'max_length'):
                    keywords_max_length = keywords_field.max_length
            except Exception as e:
                logger.warning(f"无法获取keywords字段长度限制: {str(e)}")
            
            # 计算安全截断长度（预留一些空间）
            safe_length = keywords_max_length - 100
            if safe_length < 100:
                safe_length = 100  # 确保至少有一些内容
                
            # 检查文本长度
            if len(text_content) > safe_length:
                logger.warning(f"文本长度({len(text_content)})超过安全长度({safe_length})，进行截断")
                text_content_truncated = text_content[:safe_length]
            else:
                text_content_truncated = text_content
            
            # 准备要插入的数据
            insert_data = []
            
            # 根据集合结构动态构建插入数据
            field_names = getattr(app.state, 'milvus_fields', [])
            
            # 基本字段
            data_dict = {
                "id": [doc_unique_id], 
                "file_path": [file_path],
                "embedding": [embedding]
            }
            
            # 添加keywords字段(如果存在)
            if "keywords" in field_names:
                data_dict["keywords"] = [text_content_truncated]
                
            # 添加subject字段(如果存在)
            if "subject" in field_names:
                data_dict["subject"] = [subject]
            
            # 构造插入列表
            for field in field_names:
                if field in data_dict:
                    insert_data.append(data_dict[field])
            
            # 执行插入
            if insert_data:
                collection.insert(insert_data)
                logger.info(f"文件已添加到Milvus向量数据库: {filename}")
        except Exception as e:
            logger.error(f"添加到Milvus时出错(文件仍然已保存): {str(e)}")
        
        logger.info(f"文件上传成功: {filename}")
        return {"success": True, "filename": filename, "message": f"文件已成功上传为 {filename}"}
    
    except Exception as e:
        logger.error(f"上传失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")

# 上传文件夹中的JSON文件
@app.post("/upload-directory/")
async def upload_directory(
    files: List[UploadFile] = File(...),
    keywords: str = Form("")
):
    """上传文件夹中的多个JSON文件"""
    try:
        logger.info(f"接收到上传文件夹请求，文件数量: {len(files)}")
        uploaded_files = []
        
        for file in files:
            if file.filename.endswith('.json'):
                # 获取文件名（去除路径）
                original_filename = os.path.basename(file.filename)
                logger.info(f"处理文件: {original_filename}，原始路径: {file.filename}")
                
                # 读取文件内容
                content = await file.read()
                file_content = content.decode('utf-8')
                
                # 验证JSON格式
                try:
                    json_data = json.loads(file_content)
                except json.JSONDecodeError:
                    logger.warning(f"跳过无效的JSON文件: {original_filename}")
                    continue  # 跳过无效的JSON文件
                
                # 分析文档内容确定学科
                subject = await analyze_json_content(json_data)
                logger.info(f"自动识别文件 {original_filename} 的学科为: {subject}")
                
                # 获取下一个学科特定的文档ID
                doc_id = await get_next_subject_doc_id(subject)
                filename = f"{subject}_{doc_id}.json"
                file_path = os.path.join(config.JSON_STORAGE_PATH, filename)
                
                logger.info(f"保存文件到: {file_path}")
                # 保存文件
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(json_data, f, ensure_ascii=False, indent=2)
                
                # 提取文本内容用于向量化
                text_content = ""
                if isinstance(json_data, list):
                    # 限制处理的条目数量，避免生成过长的文本
                    items_to_process = json_data[:5] if len(json_data) > 5 else json_data
                    for item in items_to_process:
                        if isinstance(item, dict):
                            # 只使用最重要的字段
                            important_fields = ['content', 'question', 'title', 'description']
                            for field in important_fields:
                                if field in item and item[field]:
                                    text_content += str(item[field]) + " "
                                    break
                            # 如果没有找到重要字段，添加前3个值
                            if not text_content and len(item) > 0:
                                text_content += " ".join(str(v) for v in list(item.values())[:3] if v)
                elif isinstance(json_data, dict):
                    # 只使用最重要的字段或前5个值
                    important_fields = ['content', 'question', 'title', 'description']
                    for field in important_fields:
                        if field in json_data and json_data[field]:
                            text_content += str(json_data[field]) + " "
                            break
                    # 如果没有找到重要字段，添加前5个值
                    if not text_content:
                        text_content += " ".join(str(v) for v in list(json_data.values())[:5] if v)
                
                # 生成向量嵌入
                embedding = generate_embedding(text_content)
                
                # 添加到Milvus向量数据库
                try:
                    collection = app.state.collection
                    doc_unique_id = str(uuid.uuid4())
                    
                    # 截断过长的文本内容，避免超出Milvus字段长度限制
                    keywords_max_length = 1000  # 默认值
                    
                    # 尝试获取字段的实际长度限制
                    try:
                        schema = collection.schema
                        keywords_field = next((f for f in schema.fields if f.name == "keywords"), None)
                        if keywords_field and hasattr(keywords_field, 'max_length'):
                            keywords_max_length = keywords_field.max_length
                    except Exception as e:
                        logger.warning(f"无法获取keywords字段长度限制: {str(e)}")
                    
                    # 计算安全截断长度（预留一些空间）
                    safe_length = keywords_max_length - 100
                    if safe_length < 100:
                        safe_length = 100  # 确保至少有一些内容
                        
                    # 检查文本长度
                    if len(text_content) > safe_length:
                        logger.warning(f"文本长度({len(text_content)})超过安全长度({safe_length})，进行截断")
                        text_content_truncated = text_content[:safe_length]
                    else:
                        text_content_truncated = text_content
                    
                    # 准备要插入的数据
                    insert_data = []
                    
                    # 根据集合结构动态构建插入数据
                    field_names = getattr(app.state, 'milvus_fields', [])
                    
                    # 基本字段
                    data_dict = {
                        "id": [doc_unique_id], 
                        "file_path": [file_path],
                        "embedding": [embedding]
                    }
                    
                    # 添加keywords字段(如果存在)
                    if "keywords" in field_names:
                        data_dict["keywords"] = [text_content_truncated]
                        
                    # 添加subject字段(如果存在)
                    if "subject" in field_names:
                        data_dict["subject"] = [subject]
                    
                    # 构造插入列表
                    for field in field_names:
                        if field in data_dict:
                            insert_data.append(data_dict[field])
                    
                    # 执行插入
                    if insert_data:
                        collection.insert(insert_data)
                        logger.info(f"文件已添加到Milvus向量数据库: {filename}")
                except Exception as e:
                    logger.error(f"添加到Milvus时出错(文件仍然已保存): {str(e)}")
                
                uploaded_files.append(filename)
        
        if not uploaded_files:
            logger.warning("没有找到有效的JSON文件")
            return {"success": False, "message": "没有找到有效的JSON文件"}
        
        logger.info(f"成功上传了 {len(uploaded_files)} 个JSON文件")
        return {
            "success": True, 
            "files": uploaded_files, 
            "count": len(uploaded_files),
            "message": f"成功上传了 {len(uploaded_files)} 个JSON文件"
        }
    
    except Exception as e:
        logger.error(f"上传失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")

# 上传历史错题文件
@app.post("/upload-history/")
async def upload_history_questions(
    subject: Optional[str] = Form(None),
    keywords: str = Form("")
):
    """上传本地error_question目录中的历史错题"""
    try:
        logger.info(f"接收到上传历史错题请求，科目: {subject or '全部'}")
        # 错题基础目录
        ERROR_BASE_DIR = "/root/error_question"
        
        # 如果未指定科目，获取所有科目的错题
        if not subject:
            # 获取所有科目目录
            subject_dirs = [d for d in os.listdir(ERROR_BASE_DIR) 
                           if os.path.isdir(os.path.join(ERROR_BASE_DIR, d)) and not d.startswith('.')]
            logger.info(f"获取所有科目: {subject_dirs}")
        else:
            # 仅获取指定科目
            if not os.path.isdir(os.path.join(ERROR_BASE_DIR, subject)):
                logger.error(f"未找到科目目录: {subject}")
                raise HTTPException(status_code=404, detail=f"未找到科目 '{subject}' 的错题目录")
            subject_dirs = [subject]
        
        uploaded_files = []
        
        # 遍历每个科目目录
        for subj in subject_dirs:
            subj_dir = os.path.join(ERROR_BASE_DIR, subj)
            json_files = [f for f in os.listdir(subj_dir) if f.endswith('.json')]
            logger.info(f"科目 {subj} 中找到 {len(json_files)} 个JSON文件")
            
            for json_file in json_files:
                src_path = os.path.join(subj_dir, json_file)
                
                # 读取JSON内容
                with open(src_path, 'r', encoding='utf-8') as f:
                    try:
                        json_data = json.load(f)
                    except json.JSONDecodeError:
                        logger.warning(f"跳过无效的JSON文件: {src_path}")
                        continue  # 跳过无效的JSON文件
                
                # 获取下一个学科特定的文档ID
                doc_id = await get_next_subject_doc_id(subj)
                new_filename = f"{subj}_{doc_id}.json"
                dest_path = os.path.join(config.JSON_STORAGE_PATH, new_filename)
                
                logger.info(f"保存文件到: {dest_path}")
                # 保存到错题文档存储目录
                with open(dest_path, "w", encoding="utf-8") as f:
                    json.dump(json_data, f, ensure_ascii=False, indent=2)
                
                # 提取文本内容用于向量化 - 使用与其他上传函数相同的逻辑
                text_content = ""
                if isinstance(json_data, list):
                    # 限制处理的条目数量，避免生成过长的文本
                    items_to_process = json_data[:5] if len(json_data) > 5 else json_data
                    for item in items_to_process:
                        if isinstance(item, dict):
                            # 只使用最重要的字段
                            important_fields = ['content', 'question', 'title', 'description']
                            for field in important_fields:
                                if field in item and item[field]:
                                    text_content += str(item[field]) + " "
                                    break
                            # 如果没有找到重要字段，添加前3个值
                            if not text_content and len(item) > 0:
                                text_content += " ".join(str(v) for v in list(item.values())[:3] if v)
                elif isinstance(json_data, dict):
                    # 只使用最重要的字段或前5个值
                    important_fields = ['content', 'question', 'title', 'description']
                    for field in important_fields:
                        if field in json_data and json_data[field]:
                            text_content += str(json_data[field]) + " "
                            break
                    # 如果没有找到重要字段，添加前5个值
                    if not text_content:
                        text_content += " ".join(str(v) for v in list(json_data.values())[:5] if v)
                
                # 生成向量嵌入
                embedding = generate_embedding(text_content)
                
                # 添加到Milvus向量数据库
                try:
                    collection = app.state.collection
                    doc_unique_id = str(uuid.uuid4())
                    
                    # 截断过长的文本内容，避免超出Milvus字段长度限制
                    keywords_max_length = 1000  # 默认值
                    
                    # 尝试获取字段的实际长度限制
                    try:
                        schema = collection.schema
                        keywords_field = next((f for f in schema.fields if f.name == "keywords"), None)
                        if keywords_field and hasattr(keywords_field, 'max_length'):
                            keywords_max_length = keywords_field.max_length
                    except Exception as e:
                        logger.warning(f"无法获取keywords字段长度限制: {str(e)}")
                    
                    # 计算安全截断长度（预留一些空间）
                    safe_length = keywords_max_length - 100
                    if safe_length < 100:
                        safe_length = 100  # 确保至少有一些内容
                        
                    # 检查文本长度
                    if len(text_content) > safe_length:
                        logger.warning(f"文本长度({len(text_content)})超过安全长度({safe_length})，进行截断")
                        text_content_truncated = text_content[:safe_length]
                    else:
                        text_content_truncated = text_content
                    
                    # 准备要插入的数据
                    insert_data = []
                    
                    # 根据集合结构动态构建插入数据
                    field_names = getattr(app.state, 'milvus_fields', [])
                    
                    # 基本字段
                    data_dict = {
                        "id": [doc_unique_id], 
                        "file_path": [dest_path],
                        "embedding": [embedding]
                    }
                    
                    # 添加keywords字段(如果存在)
                    if "keywords" in field_names:
                        data_dict["keywords"] = [text_content_truncated]
                        
                    # 添加subject字段(如果存在)
                    if "subject" in field_names:
                        data_dict["subject"] = [subj]  # 直接使用科目文件夹名称
                    
                    # 构造插入列表
                    for field in field_names:
                        if field in data_dict:
                            insert_data.append(data_dict[field])
                    
                    # 执行插入
                    if insert_data:
                        collection.insert(insert_data)
                        logger.info(f"文件已添加到Milvus向量数据库: {new_filename}")
                except Exception as e:
                    logger.error(f"添加到Milvus时出错(文件仍然已保存): {str(e)}")
                
                uploaded_files.append({
                    "filename": new_filename,
                    "original": json_file,
                    "subject": subj
                })
        
        if not uploaded_files:
            logger.warning("没有找到有效的历史错题文件")
            return {"success": False, "message": "没有找到有效的历史错题文件"}
        
        logger.info(f"成功上传了 {len(uploaded_files)} 个历史错题文件")
        return {
            "success": True, 
            "files": uploaded_files, 
            "count": len(uploaded_files),
            "message": f"成功上传了 {len(uploaded_files)} 个历史错题文件"
        }
    
    except Exception as e:
        logger.error(f"上传历史错题失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"上传历史错题失败: {str(e)}")

# Search documents endpoint
@app.post("/documents/search/")
async def search_documents(query: SearchQuery):
    try:
        # 生成查询向量
        query_embedding = generate_embedding(query.keyword)
        
        # 在Milvus中搜索
        collection = app.state.collection
        search_params = {"metric_type": "L2", "params": {"nprobe": 16}}
        
        # 获取输出字段列表，确保包含必要字段
        output_fields = ["file_path"]
        
        # 构建查询表达式，如果指定了学科，则按学科筛选
        expr = None
        if query.subject:
            # 检查集合是否有subject字段
            field_names = [field.name for field in collection.schema.fields]
            if 'subject' in field_names:
                expr = f'subject == "{query.subject}"'
                logger.info(f"按学科筛选搜索: {query.subject}")
                # 如果有subject字段，添加到输出字段
                if "subject" not in output_fields:
                    output_fields.append("subject")
            else:
                logger.warning(f"集合中不存在subject字段，无法按学科筛选")
        
        # 向量搜索
        try:
            results = collection.search(
                data=[query_embedding],
                anns_field="embedding",
                param=search_params,
                limit=query.limit,
                output_fields=output_fields,
                expr=expr
            )
            logger.info(f"Milvus搜索成功，找到 {len(results[0])} 个结果")
        except Exception as e:
            logger.error(f"Milvus搜索失败，切换到备用搜索: {str(e)}")
            raise e  # 直接抛出异常，让备用搜索处理
        
        # 获取文件路径
        file_paths = [hit.entity.get('file_path') for hit in results[0]]
        
        # 加载文档
        documents = []
        for file_path in file_paths:
            try:
                # 检查文件是否存在
                if not os.path.exists(file_path):
                    logger.warning(f"文件不存在，可能已被删除: {file_path}")
                    continue
                    
                async with aiofiles.open(file_path, 'r') as f:
                    content = await f.read()
                    file_name = os.path.basename(file_path)
                    
                    # 处理文件名格式，支持数字序号格式(1.json)和学科_ID格式(math_1.json)
                    if '_' in file_name:
                        # 学科_ID格式
                        subject, doc_id = file_name.split('_', 1)
                        doc_id = doc_id.split('.')[0]  # 去掉.json后缀
                    else:
                        # 纯数字序号格式
                        doc_id = file_name.split('.')[0]  # 去掉.json后缀
                        subject = "未分类"
                    
                    documents.append({
                        "id": doc_id,
                        "subject": subject,
                        "file_name": file_name,
                        "content": json.loads(content)
                    })
            except FileNotFoundError:
                logger.error(f"文件不存在: {file_path}")
            except Exception as e:
                logger.error(f"处理文件 {file_path} 时出错: {str(e)}")
        
        return {"results": documents}
    
    except Exception as e:
        logger.error(f"搜索文档失败: {str(e)}")
        # 备用文件系统搜索
        try:
            # 获取所有文档
            files = os.listdir(config.JSON_STORAGE_PATH)
            json_files = [f for f in files if f.endswith('.json')]
            
            # 如果指定了学科，按学科筛选
            if query.subject:
                json_files = [f for f in json_files if f.startswith(f"{query.subject}_")]
            
            # 加载并过滤文档
            documents = []
            for file_name in json_files:
                file_path = os.path.join(config.JSON_STORAGE_PATH, file_name)
                # 检查文件是否存在
                if not os.path.exists(file_path):
                    logger.warning(f"备用搜索：文件不存在，可能已被删除: {file_path}")
                    continue
                    
                try:
                    async with aiofiles.open(file_path, 'r') as f:
                        content = await f.read()
                        # 检查关键词是否在内容中
                        if query.keyword.lower() in content.lower():
                            # 从文件名中提取信息
                            # 处理文件名格式，支持数字序号格式(1.json)和学科_ID格式(math_1.json)
                            if '_' in file_name:
                                # 学科_ID格式
                                subject, doc_id = file_name.split('_', 1)
                                doc_id = doc_id.split('.')[0]  # 去掉.json后缀
                            else:
                                # 纯数字序号格式
                                doc_id = file_name.split('.')[0]  # 去掉.json后缀
                                subject = "未分类"
                            
                            documents.append({
                                "id": doc_id,
                                "subject": subject,
                                "file_name": file_name,
                                "content": json.loads(content)
                            })
                        
                        # 限制结果数量
                        if len(documents) >= query.limit:
                            break
                except Exception as e:
                    logger.error(f"备用搜索：处理文件 {file_path} 时出错: {str(e)}")
                    continue
            
            return {"results": documents}
        except Exception as e2:
            logger.error(f"备用搜索也失败: {str(e2)}")
            raise HTTPException(status_code=500, detail=f"Failed to search documents: {str(e)}, {str(e2)}")

# 前端API接口的搜索
@app.post("/api/search/")
async def api_search(
    keyword: str = Form(...), 
    subject: str = Form(None),
    limit: int = Form(10)
):
    try:
        query = SearchQuery(keyword=keyword, subject=subject, limit=limit)
        
        # 直接尝试备用搜索方法
        try:
            # 获取所有文档
            logger.info(f"使用备用搜索方法：关键词={keyword}, 学科={subject}, 限制={limit}")
            files = os.listdir(config.JSON_STORAGE_PATH)
            json_files = [f for f in files if f.endswith('.json')]
            
            # 如果指定了学科，按学科筛选
            if subject and subject.strip():
                # 使用两种筛选方式: 
                # 1. 学科_ID.json 格式
                # 2. 如果文件内容包含学科信息
                subject_files = []
                
                # 首先检查文件名是否以学科为前缀
                subject_files = [f for f in json_files if f.startswith(f"{subject}_")]
                logger.info(f"按文件名前缀筛选到 {len(subject_files)} 个 {subject} 学科文件")
                
                # 如果没有找到符合条件的文件，则检查所有文件
                if not subject_files:
                    logger.info(f"未找到学科为 {subject} 的文件，进行全文搜索")
                    json_files = json_files
                else:
                    json_files = subject_files
            
            # 加载并过滤文档
            documents = []
            for file_name in json_files:
                file_path = os.path.join(config.JSON_STORAGE_PATH, file_name)
                # 检查文件是否存在
                if not os.path.exists(file_path):
                    logger.warning(f"文件不存在: {file_path}")
                    continue
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                        # 检查关键词是否在内容中
                        if keyword.lower() in content.lower():
                            # 从文件名中提取信息
                            # 处理文件名格式，支持数字序号格式(1.json)和学科_ID格式(math_1.json)
                            if '_' in file_name:
                                # 学科_ID格式
                                file_subject, doc_id = file_name.split('_', 1)
                                doc_id = doc_id.split('.')[0]  # 去掉.json后缀
                            else:
                                # 纯数字序号格式
                                doc_id = file_name.split('.')[0]  # 去掉.json后缀
                                file_subject = "未分类"
                            
                            documents.append({
                                "id": doc_id,
                                "subject": file_subject,
                                "file_name": file_name,
                                "content": json.loads(content)
                            })
                            
                            # 限制结果数量
                            if len(documents) >= limit:
                                break
                except Exception as e:
                    logger.error(f"处理文件 {file_path} 时出错: {str(e)}")
            
            logger.info(f"搜索完成，找到 {len(documents)} 个结果")
            return {"results": documents}
            
        except Exception as e:
            logger.error(f"备用搜索方法失败: {str(e)}")
            # 如果备用方法失败，尝试标准搜索
            return await search_documents(query)
            
    except Exception as e:
        logger.error(f"API搜索失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")

# 添加GET方法的搜索接口，支持URL参数
@app.get("/search/")
async def get_search(
    keyword: str = Query(...),
    subject: Optional[str] = Query(None),
    limit: int = Query(10)
):
    # 直接使用POST API搜索，避免代码重复
    try:
        # 创建表单数据
        form_data = {
            'keyword': keyword,
            'subject': subject if subject else '',
            'limit': str(limit)
        }
        
        # 调用POST方法
        return await api_search(**form_data)
    except Exception as e:
        logger.error(f"GET搜索接口错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")

# 获取所有文档
@app.get("/documents/")
async def get_all_documents():
    """获取所有文档"""
    try:
        logger.info("获取所有文档")
        documents = []
        json_files = glob.glob(os.path.join(config.JSON_STORAGE_PATH, "*.json"))
        logger.info(f"找到 {len(json_files)} 个JSON文件")
        
        for file_path in json_files:
            try:
                filename = os.path.basename(file_path)
                file_size = os.path.getsize(file_path)
                file_created = os.path.getctime(file_path)
                logger.debug(f"处理文件: {filename}")
                
                # 从文件名中提取信息
                doc_id = filename
                subject = ""  # 默认为空字符串而不是"未分类"
                if '_' in filename:
                    # 学科_ID格式
                    subject, doc_id_part = filename.split('_', 1)
                    doc_id = doc_id_part.split('.')[0]  # 去掉.json后缀
                else:
                    # 纯数字序号格式
                    doc_id = filename.split('.')[0]  # 去掉.json后缀
                
                # 读取内容并生成预览
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    json_data = json.loads(content)
                
                # 提取预览内容
                preview = ""
                try:
                    if isinstance(json_data, list) and len(json_data) > 0:
                        first_item = json_data[0]
                        if isinstance(first_item, dict):
                            # 尝试获取内容字段
                            for field in ['content', 'question', 'title', 'description']:
                                if field in first_item and first_item[field]:
                                    preview = str(first_item[field])[:100] + '...'
                                    break
                            # 如果没有找到特定字段，使用第一个非空值
                            if not preview and first_item:
                                for value in first_item.values():
                                    if value:
                                        preview = str(value)[:100] + '...'
                                        break
                    elif isinstance(json_data, dict):
                        values = list(json_data.values())
                        if values:
                            preview = str(values[0])[:100] + '...'
                except Exception as e:
                    logger.warning(f"生成预览内容时出错: {str(e)}")
                    # 不设置默认的预览内容
                
                documents.append({
                    "id": doc_id,
                    "filename": filename,
                    "file_name": filename,  # 提供两种名称格式确保兼容性
                    "subject": subject,
                    "size": file_size,
                    "preview": preview,
                    "created": file_created
                })
            except Exception as e:
                logger.error(f"处理文件 {file_path} 时出错: {e}")
        
        # 按创建时间排序
        documents.sort(key=lambda x: x["created"], reverse=True)
        
        logger.info(f"返回 {len(documents)} 个文档")
        return {"documents": documents, "count": len(documents)}
    except Exception as e:
        logger.error(f"获取所有文档失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取文档失败: {str(e)}")

# 获取文档内容
@app.get("/document/{doc_id}")
async def get_document(doc_id: str):
    """获取文档内容"""
    try:
        logger.info(f"获取文档内容: {doc_id}")
        
        # 尝试不同的可能路径
        possible_paths = [
            os.path.join(config.JSON_STORAGE_PATH, doc_id),  # 完整路径（如果doc_id已经包含.json后缀）
            os.path.join(config.JSON_STORAGE_PATH, f"{doc_id}.json"),  # 添加.json后缀
        ]
        
        # 如果doc_id是纯数字，还要尝试找到对应学科的文件
        if doc_id.isdigit():
            # 查找所有可能匹配的文件
            pattern = f"*_{doc_id}.json"
            matching_files = glob.glob(os.path.join(config.JSON_STORAGE_PATH, pattern))
            if matching_files:
                possible_paths.append(matching_files[0])  # 添加第一个匹配的文件
        
        # 尝试每个可能的路径
        file_path = None
        for path in possible_paths:
            if os.path.exists(path):
                file_path = path
                break
        
        if not file_path:
            logger.error(f"文档不存在: 尝试了以下路径: {possible_paths}")
            raise HTTPException(status_code=404, detail="文档不存在")
        
        # 获取文件基本信息
        file_stat = os.stat(file_path)
        file_size = file_stat.st_size
        file_created = file_stat.st_ctime
        
        # 从文件名中提取学科信息
        subject = ""  # 默认为空字符串而不是"未分类"
        filename = os.path.basename(file_path)
        if '_' in filename:
            # 学科_ID格式
            subject, _ = filename.split('_', 1)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = json.load(f)
        
        # 生成预览内容
        preview = ""
        try:
            if isinstance(content, list) and len(content) > 0:
                first_item = content[0]
                if isinstance(first_item, dict):
                    preview = str(first_item.get('content', ''))[:100] + '...'
            elif isinstance(content, dict):
                values = list(content.values())
                if values:
                    preview = str(values[0])[:100] + '...'
        except Exception as e:
            logger.warning(f"生成预览内容时出错: {str(e)}")
            # 不设置默认的预览内容
        
        # 返回完整的文档信息
        return {
            "id": doc_id,
            "file_name": filename,
            "file_path": file_path,
            "subject": subject,
            "content": content,
            "preview": preview,
            "size": file_size,
            "created": file_created
        }
    except json.JSONDecodeError:
        logger.error(f"无效的JSON格式: {doc_id}")
        raise HTTPException(status_code=400, detail="无效的JSON格式")
    except Exception as e:
        logger.error(f"获取文档失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取文档失败: {str(e)}")

# 清理所有数据
@app.post("/cleanup/")
async def cleanup_data():
    """清理所有数据"""
    try:
        logger.info("清理所有数据")
        # 清空JSON存储目录
        for file in os.listdir(config.JSON_STORAGE_PATH):
            file_path = os.path.join(config.JSON_STORAGE_PATH, file)
            if os.path.isfile(file_path):
                os.remove(file_path)
                logger.info(f"删除文件: {file_path}")
        
        # 尝试清空Milvus集合
        try:
            collection = app.state.collection
            # 由于Milvus可能会限制删除方式，我们尝试释放并删除整个集合
            collection.release()
            utility.drop_collection(config.COLLECTION_NAME)
            logger.info(f"删除并重建Milvus集合: {config.COLLECTION_NAME}")
            
            # 重新初始化Milvus
            app.state.collection = await init_milvus()
        except Exception as e:
            logger.warning(f"清理Milvus数据时出错: {str(e)}")
            logger.info("继续执行，仅清理了文件")
        
        return {"success": True, "message": "所有数据已成功清理"}
    except Exception as e:
        logger.error(f"清理数据失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"清理数据失败: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5003) 