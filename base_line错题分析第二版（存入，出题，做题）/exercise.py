import os
import webbrowser
import random
import datetime
from fastapi import FastAPI, Body, Request, Query, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any, Optional
import json
import threading
import time
import uvicorn
import config

# 文件夹路径设置
TEST_FILES_DIR = "/root/create_new_test"  # 出题文件夹
ERROR_BASE_DIR = "/root/error_question"  # 错题基础目录
STATIC_DIR = "static"
PORT = 5004

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

# 文件名映射（确保与前端的科目值对应）
FILE_TO_SUBJECT = {
    'new_questions_math.json': 'math',
    'new_questions_history.json': 'history',
    'new_questions_chinese.json': 'chinese',
    'new_questions_english.json': 'english',
    'new_questions_geography.json': 'geography',
    'new_questions_politics.json': 'politics',
    'new_questions_chemistry.json': 'chemistry',
    'new_questions_biology.json': 'biology',
    'new_questions_physics.json': 'physics'
}

# 确保错题基础目录存在
os.makedirs(ERROR_BASE_DIR, exist_ok=True)

# 为每个科目创建错题目录
for subject in SUBJECT_NAMES.keys():
    os.makedirs(os.path.join(ERROR_BASE_DIR, subject), exist_ok=True)

app = FastAPI()

# 正确做法：静态文件挂载到 /static
app.mount("/static", StaticFiles(directory=STATIC_DIR, html=True), name="static")

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境需要修改为特定域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 主页路由，返回 index.html
@app.get("/")
def main():
    """返回主页"""
    return FileResponse(os.path.join(STATIC_DIR, "index_base.html"))

# 获取所有可用科目
@app.get("/subjects")
def get_subjects():
    """获取所有可用的科目"""
    try:
        json_files = [f for f in os.listdir(TEST_FILES_DIR) if f.endswith('.json')]
        print(f"找到JSON文件: {json_files}")
        subjects = []
        
        for file in json_files:
            # 从文件名映射中获取科目
            if file in FILE_TO_SUBJECT:
                subjects.append(FILE_TO_SUBJECT[file])
        
        print(f"可用科目: {subjects}")
        return {"subjects": subjects}
    except Exception as e:
        print(f"获取科目列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取科目列表失败: {str(e)}")

def get_test_file_by_subject(subject: Optional[str] = None) -> str:
    """根据科目获取试题文件"""
    json_files = [f for f in os.listdir(TEST_FILES_DIR) if f.endswith('.json')]
    
    if not json_files:
        raise Exception(f"在 {TEST_FILES_DIR} 中没有找到JSON文件")
    
    if subject:
        # 查找指定科目的文件
        for file in json_files:
            if file in FILE_TO_SUBJECT and FILE_TO_SUBJECT[file] == subject:
                return os.path.join(TEST_FILES_DIR, file)
        
        raise Exception(f"未找到科目 '{subject}' 的试题文件")
    else:
        # 如果未指定科目，随机选择一个
        return os.path.join(TEST_FILES_DIR, random.choice(json_files))

def read_exam(subject: Optional[str] = None) -> Dict[str, Any]:
    """读取试卷数据"""
    try:
        test_file = get_test_file_by_subject(subject)
        print(f"正在使用试卷文件: {test_file}")
        
        # 从文件名获取科目
        file_basename = os.path.basename(test_file)
        file_subject = FILE_TO_SUBJECT.get(file_basename, subject)
        subject_display = SUBJECT_NAMES.get(file_subject, file_subject) if file_subject else "随机科目"
        
        with open(test_file, "r", encoding="utf-8") as f:
            file_content = json.load(f)
            
            # 处理不同的文件格式
            if isinstance(file_content, list):
                # 如果是数组格式，转换为对象格式
                data = {
                    "title": f"2025年全国卷{subject_display}模拟试卷",
                    "questions": file_content
                }
            else:
                # 如果已经是对象格式
                data = file_content
                # 更新试卷标题
                data["title"] = f"2025年全国卷{subject_display}模拟试卷"
                
            return data
    except FileNotFoundError:
        raise Exception(f"试卷文件未找到")
    except json.JSONDecodeError:
        raise Exception(f"试卷文件JSON格式错误")
    except Exception as e:
        raise Exception(f"读取试卷失败: {e}")

def save_wrong_questions(wrong_list: List[Dict[str, Any]], subject: Optional[str] = None):
    """
    保存错题列表到文件，按科目分类存储，每次创建新文件
    """
    try:
        if not wrong_list:
            return
        
        # 确定科目
        if subject:
            subject_dir = os.path.join(ERROR_BASE_DIR, subject)
        else:
            # 如果没有指定科目，尝试从第一道错题中获取科目信息
            first_question = wrong_list[0]
            # 遍历FILE_TO_SUBJECT的反向映射，查找科目
            found_subject = None
            for file_name, subj in FILE_TO_SUBJECT.items():
                if subj in first_question.get("content", "").lower():
                    found_subject = subj
                    break
            
            # 如果找不到科目，使用默认目录
            if found_subject:
                subject_dir = os.path.join(ERROR_BASE_DIR, found_subject)
            else:
                subject_dir = os.path.join(ERROR_BASE_DIR, "other")
                os.makedirs(subject_dir, exist_ok=True)
        
        # 生成时间戳作为文件名的一部分
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 查找当前科目目录下的文件数量，用于命名
        existing_files = [f for f in os.listdir(subject_dir) if f.endswith('.json')]
        file_count = len(existing_files) + 1
        
        # 创建新的错题文件
        wrong_file = os.path.join(subject_dir, f"{subject}_{file_count}.json")
        
        with open(wrong_file, "w", encoding="utf-8") as f:
            json.dump(wrong_list, f, ensure_ascii=False, indent=2)
            
        print(f"错题已保存到: {wrong_file}")

    except Exception as e:
        print(f"保存错题失败: {e}")  # 打印错误信息，但不中断程序

@app.get("/exam")
def get_exam(subject: Optional[str] = Query(None, description="科目名称，如 math, history 等")):
    """获取试卷数据"""
    try:
        print(f"收到请求获取科目: {subject}")
        data = read_exam(subject)
        print(f"成功读取试卷数据，标题: {data.get('title', '未知')}")
        return data
    except Exception as e:
        print(f"获取试卷数据失败: {str(e)}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/submit")
def submit_exam(user_answers: List[str] = Body(...), subject: Optional[str] = Query(None)):
    """提交试卷，返回判题结果"""
    try:
        exam_data = read_exam(subject)
        questions = exam_data.get("questions", [])
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"试卷读取失败: {e}"})

    if len(user_answers) != len(questions):
        return JSONResponse(status_code=400, content={"error": "用户答案数量与题目数量不一致"})

    results = []
    wrong_list = []
    for q, ua in zip(questions, user_answers):
        is_correct = str(ua).strip() == str(q['correct_answer']).strip()
        result_item = {
            "id": q["id"],
            "type": q["type"],
            "score": q["score"],
            "content": q["content"],
            "options": q.get("options", []),
            "knowledge_points": q["knowledge_points"],
            "user_answer": ua,
            "correct_answer": q["correct_answer"],
            "is_correct": is_correct
        }
        results.append(result_item)
        if not is_correct:
            wrong_list.append(result_item)

    if wrong_list:
        # 获取当前正在做的科目
        current_subject = subject
        if not current_subject:
            # 如果没有指定科目，尝试从文件名判断
            test_file = get_test_file_by_subject(None)
            file_basename = os.path.basename(test_file)
            current_subject = FILE_TO_SUBJECT.get(file_basename, "other")
            
        save_wrong_questions(wrong_list, current_subject)

    return {
        "results": results,
        "wrong_count": len(wrong_list),
        "right_count": len(questions) - len(wrong_list),
        "total": len(questions)
    }

if __name__ == '__main__':
    def open_browser():
        time.sleep(1.2)
        webbrowser.open(f"http://localhost:{PORT}")

    print(f"正在启动服务，请稍候...")
    threading.Thread(target=open_browser).start()
    uvicorn.run(app, host='0.0.0.0', port=PORT)