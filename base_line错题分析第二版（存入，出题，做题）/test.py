import json
import re
import os  # 导入 os 模块用于文件系统操作
from openai import OpenAI  # 确保你安装了 openai-python SDK，适配 GLM

# ===== 1. 初始化 GLM 客户端（替换成你的 API KEY 和 Base URL） =====
client = OpenAI(
    api_key="sk-b4a88b610f07423d8aef4a96a7d3e79f",
    base_url="https://api.deepseek.com"
)


# ===== 2. 读取错题数据 =====
def load_wrong_questions(directory_path, subject=None):
    """
    从指定目录加载错题数据，并可选地按科目筛选。

    Args:
        directory_path (str): 包含错题JSON文件的目录路径。
        subject (str, optional): 要筛选的科目名称（英文小写，如 "math", "english", "chinese"）。
                                 只有文件名中包含该科目的文件才会被加载。
                                 默认为 None，表示加载所有文件。

    Returns:
        list: 包含所有符合条件的错题字典的列表。
    """
    all_wrong_questions = []
    if not os.path.isdir(directory_path):
        print(f"❌ 错误：目录 '{directory_path}' 不存在。请创建该目录并放入错题JSON文件。")
        return []

    print(f"📂 正在从目录 '{directory_path}' 加载错题数据...")
    if subject:
        # 将传入的科目名称转换为小写，用于不区分大小写的匹配
        subject_lower = subject.lower()
        print(f"🔍 仅加载科目为 '{subject}' 的错题...")

    for filename in os.listdir(directory_path):
        if filename.endswith(".json"):
            file_path = os.path.join(directory_path, filename)

            # 如果指定了科目，并且文件名（转换为小写）中不包含该科目（转换为小写），则跳过此文件
            if subject and subject_lower not in filename.lower():
                print(f"跳过文件：'{filename}' (不包含科目 '{subject}')")
                continue

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 检查 JSON 数据是列表还是包含 "questions" 键的字典
                    if isinstance(data, list):
                        all_wrong_questions.extend(data)
                        print(f"✅ 从 '{filename}' 加载了 {len(data)} 道题目。")
                    elif isinstance(data, dict) and "questions" in data and isinstance(data["questions"], list):
                        all_wrong_questions.extend(data["questions"])
                        print(f"✅ 从 '{filename}' 加载了 {len(data['questions'])} 道题目。")
                    else:
                        print(
                            f"⚠️ 文件 '{filename}' 的内容格式不符合预期（既不是题目列表也不是包含 'questions' 键的字典），跳过。")
            except json.JSONDecodeError as e:
                print(f"❌ 解析文件 '{filename}' 失败：{e}")
            except Exception as e:
                print(f"❌ 读取文件 '{filename}' 时发生错误：{e}")

    print(f"✨ 共加载了 {len(all_wrong_questions)} 道符合条件的错题。")
    return all_wrong_questions


# ===== 3. 构建提示词 =====
def build_prompt(questions):
    """
    根据提供的错题数据构建用于生成新题的提示词。

    Args:
        questions (list): 错题字典的列表。

    Returns:
        str: 构建好的提示词。
    """
    prompt = """你是一位经验丰富的高考命题专家。我将提供一组高考试题错题作为参考数据，请你不要对这些题目进行任何修改或复用，仅分析其**题型类型**和**所涉及的知识点类型**，并根据这些分析结果**重新创作出一批全新试题**。

请你严格按照以下要求进行命题：

1. **出题依据为题型（type）和题型逻辑结构**，而不是内容简单变形；
2. **在保持原有错题所涉及的知识点类型（例如：函数性质、几何证明、历史事件分析、文学作品主题分析等）一致的前提下，题干、选项、情境设置、解答角度必须完全原创，绝不允许：**
   - 复用原题文本的任何部分
   - 构造与原题内容相似但形式不同的题目（同题异构）
   - 保留原题的设问方式或核心情境
3. **确保每道题逻辑清晰、有独立构思和新颖表达**；
4. **语言必须符合高考正式命题规范，题型排布与真实高考试卷一致，确保题目完整性与科学性**；
5. **题目排序必须遵循以下顺序：先是所有选择题，然后是所有填空题，最后是所有大题（解答题/作文题）**；
6. **每道题必须包含以下字段**：
   - `id`: 自定义编号
   - `type`: "choice" 表示选择题, "fill_blank" 表示填空题, 或 "essay" 表示大题/解答题
   - `score`: 分值
   - `content`: 题干内容（必须原创）
   - `options`: 若非选择题则为 `[]`
   - `knowledge_points`: 涉及知识点数组 (请确保这里的知识点是该题实际考察的，且与原题的知识点类型保持一致，但具体表述和应用场景必须原创)
   - `user_answer`: 始终设置为 `""`
   - `correct_answer`: 正确答案或结论，**必须有值，不提供解题过程**

7. 输出请严格采用如下 JSON 格式：
{
  "exam_name": "2025年全国卷模拟试卷",
  "questions": [
    {
      "id": 1,
      "type": "choice",
      "score": 5,
      "content": "题干内容...",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
      "knowledge_points": ["..."],
      "user_answer": "",
      "correct_answer": "..."
    }
  ]
}

下面是需要分析题型的错题数据：
"""

    # 添加每道错题（只用于题型参考，不用于复用）
    if not questions:
        prompt += "\n未找到符合条件的错题数据，请检查目录和科目设置，或提供的错题数据为空。"
    else:
        for q in questions:
            # 使用 .get() 方法安全地访问字典键，提供默认值以防键不存在
            prompt += f"\n题型：{q.get('type', '未知')}，分值：{q.get('score', 0)}分\n"
            prompt += f"题干：{q.get('content', '无题干')}\n"
            prompt += f"知识点：{', '.join(q.get('knowledge_points', []))}\n"

    prompt += "\n请根据这些题型结构和知识点类型创作全新试题，并返回严格 JSON 格式内容。再次强调，题目必须按照选择题、填空题、大题的顺序排列。"
    return prompt


# ===== 4. 调用 GLM 模型生成新题 =====
def generate_exam(prompt):
    """
    调用 GLM 模型生成新的试卷内容。

    Args:
        prompt (str): 包含生成指令和错题数据的提示词。

    Returns:
        str: 模型返回的原始文本内容。
    """
    print("⏳ 正在调用大模型生成试卷，请稍候...")
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=4000
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ 调用大模型失败：{e}")
        return ""


# ===== 5. 提取 JSON 并调整字段顺序 =====
def extract_json(text):
    """
    从模型返回的文本中提取 JSON 格式的新题目列表，并按题型排序：选择题 -> 填空题 -> 大题。

    Args:
        text (str): 模型返回的原始文本。

    Returns:
        list: 格式化后的新题目字典列表。如果解析失败，返回空列表。
    """
    try:
        # 匹配最外层的 JSON 对象，因为模型输出是 {"exam_name": ..., "questions": [...]} 结构
        # 调整正则表达式以更精确地匹配 JSON 对象，例如以 { 开头并以 } 结尾
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            print("⚠️ 未从模型输出中提取到完整的 JSON 对象。")
            return []

        raw_exam_data = json.loads(match.group())

        # 确保提取的数据是字典且包含 'questions' 键，并且 'questions' 是一个列表
        if not isinstance(raw_exam_data, dict) or "questions" not in raw_exam_data or not isinstance(
                raw_exam_data["questions"], list):
            print("⚠️ 提取的 JSON 格式不符合预期，缺少 'questions' 列表或结构不正确。")
            return []

        # 先处理所有题目
        all_questions = []
        for item in raw_exam_data["questions"]:
            all_questions.append({
                "id": item.get("id", 0),  # 使用 .get() 提供默认值
                "type": item.get("type", ""),
                "score": item.get("score", 0),
                "content": item.get("content", ""),
                "options": item.get("options", []),
                "knowledge_points": item.get("knowledge_points", []),
                "user_answer": "",  # 始终为空，前端作答
                "correct_answer": item.get("correct_answer", "")
            })
        
        # 按题型分类并排序
        choice_questions = [q for q in all_questions if q["type"] == "choice"]
        fill_blank_questions = [q for q in all_questions if q["type"] == "fill_blank"]
        essay_questions = [q for q in all_questions if q["type"] == "essay"]
        other_questions = [q for q in all_questions if q["type"] not in ["choice", "fill_blank", "essay"]]
        
        # 按照"先选择题，后填空题，最后是大题"的顺序重新组合题目
        sorted_questions = choice_questions + fill_blank_questions + essay_questions + other_questions
        
        # 重新分配题目ID
        for i, question in enumerate(sorted_questions, 1):
            question["id"] = i
            
        print(f"✅ 题目已按照题型排序：选择题({len(choice_questions)}道) -> 填空题({len(fill_blank_questions)}道) -> 大题({len(essay_questions)}道) -> 其他({len(other_questions)}道)")
        
        return sorted_questions

    except json.JSONDecodeError as e:
        print(f"❌ JSON解析失败：{e}")
        # 打印导致解析失败的文本片段，便于调试
        if match:
            print(
                f"尝试解析的文本片段（前后100字符）：\n{text[max(0, match.start() - 100):min(len(text), match.end() + 100)]}")
        else:
            print(f"原始文本：\n{text}")
        return []
    except Exception as e:
        print(f"❌ 处理提取的 JSON 数据时发生错误：{e}")
        return []


# ===== 6. 主程序入口 =====
if __name__ == "__main__":
    wrong_docs_directory = "wrong_docs"  # 错题数据文件夹路径
    create_new_test_directory = "create_new_test"  # 新增：生成新题的保存目录

    # 提示用户输入科目名称
    print("\n请选择要生成新题的科目（例如：math, english, chinese）:")
    selected_subject = input("请输入科目名称: ").strip().lower()  # 将用户输入转换为小写，方便匹配

    if not selected_subject:
        print("❌ 未输入科目名称，程序退出。")
    else:
        # 构建输出文件名，例如 new_questions_math.json
        output_filename = f"new_questions_{selected_subject}.json"
        # 构建完整的输出文件路径，包含新目录
        output_full_path = os.path.join(create_new_test_directory, output_filename)

        # Step 1: 加载错题
        # 调用修改后的函数，传入目录和用户选择的科目
        wrong_questions = load_wrong_questions(wrong_docs_directory, selected_subject)

        if not wrong_questions:
            print(
                f"未找到科目 '{selected_subject}' 的错题数据，或加载失败，无法生成新题。请检查 '{wrong_docs_directory}' 目录和文件命名。")
        else:
            # Step 2: 构建提示词
            prompt = build_prompt(wrong_questions)

            # Step 3: 调用真实 GLM 接口
            model_response = generate_exam(prompt)

            # Step 4: 提取结构化新题
            new_questions = extract_json(model_response)

            if new_questions:
                # 新增：创建目标文件夹（如果不存在）
                try:
                    os.makedirs(create_new_test_directory, exist_ok=True)
                    print(f"✅ 确保目录 '{create_new_test_directory}' 存在。")
                except OSError as e:
                    print(f"❌ 无法创建目录 '{create_new_test_directory}': {e}")
                    exit() # 如果目录无法创建，则无法保存文件，直接退出

                # 统计题型分布
                choice_count = sum(1 for q in new_questions if q["type"] == "choice")
                fill_blank_count = sum(1 for q in new_questions if q["type"] == "fill_blank")
                essay_count = sum(1 for q in new_questions if q["type"] == "essay")
                other_count = sum(1 for q in new_questions if q["type"] not in ["choice", "fill_blank", "essay"])
                
                # 计算总分值
                total_score = sum(q["score"] for q in new_questions)

                # Step 5: 保存到文件
                try:
                    with open(output_full_path, 'w', encoding='utf-8') as f:
                        json.dump(new_questions, f, ensure_ascii=False, indent=2)
                    print(f"✅ 新题已生成并保存至：{output_full_path}")
                    print(f"📊 试卷统计：")
                    print(f"   - 总题数: {len(new_questions)} 道")
                    print(f"   - 总分值: {total_score} 分")
                    print(f"   - 选择题: {choice_count} 道")
                    print(f"   - 填空题: {fill_blank_count} 道")
                    print(f"   - 大题/解答题: {essay_count} 道")
                    if other_count > 0:
                        print(f"   - 其他题型: {other_count} 道")
                except Exception as e:
                    print(f"❌ 保存新题到文件失败：{e}")
            else:
                print("❌ 未能成功生成新题，请检查模型输出或JSON解析逻辑。")