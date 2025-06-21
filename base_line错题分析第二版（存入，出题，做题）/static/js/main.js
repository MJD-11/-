/**
 * 错题文档管理系统 - 前端JavaScript
 */

// 美化JSON显示
function formatJSON(json) {
    if (typeof json !== 'string') {
        json = JSON.stringify(json, null, 2);
    }
    
    // 替换HTML特殊字符，防止XSS攻击
    json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    
    // 高亮显示JSON语法
    return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, function (match) {
        let cls = 'number';
        if (/^"/.test(match)) {
            if (/:$/.test(match)) {
                cls = 'key';
            } else {
                cls = 'string';
            }
        } else if (/true|false/.test(match)) {
            cls = 'boolean';
        } else if (/null/.test(match)) {
            cls = 'null';
        }
        return '<span class="' + cls + '">' + match + '</span>';
    });
}

// 在页面加载完成后执行
document.addEventListener('DOMContentLoaded', function() {
    // 加载科目列表
    loadSubjects();
    
    // 美化JSON显示的辅助函数
    window.prettyPrintJSON = function(element, jsonData) {
        if (element) {
            element.classList.add('json-highlight');
            element.innerHTML = formatJSON(jsonData);
        }
    };
    
    // 上传单个JSON文件
    const uploadFileForm = document.getElementById('uploadFileForm');
    if (uploadFileForm) {
        uploadFileForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const fileInput = document.getElementById('jsonFile');
            const keywordsInput = document.getElementById('fileKeywords');
            const successAlert = document.getElementById('fileUploadSuccess');
            const errorAlert = document.getElementById('fileUploadError');
            
            if (!fileInput.files.length) {
                showError(errorAlert, '请选择一个JSON文件');
                return;
            }
            
            const file = fileInput.files[0];
            if (!file.name.endsWith('.json')) {
                showError(errorAlert, '请选择JSON格式的文件');
                return;
            }
            
            // 显示上传中状态
            const submitBtn = uploadFileForm.querySelector('button[type="submit"]');
            const originalBtnText = submitBtn.innerHTML;
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> 上传中...';
            
            const formData = new FormData();
            formData.append('file', file);
            formData.append('keywords', keywordsInput.value);  // 变量名保持不变，但实际是备注
            
            fetch('/upload/', {
                method: 'POST',
                body: formData
            })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(data => {
                        throw new Error(data.detail || '上传文件失败');
                    });
                }
                return response.json();
            })
            .then(data => {
                showSuccess(successAlert, `<i class="bi bi-check-circle"></i> ${data.message}`);
                uploadFileForm.reset();
                // 重置文件上传区域的文本
                const fileUploadArea = uploadFileForm.querySelector('.file-upload-area p');
                if (fileUploadArea) {
                    fileUploadArea.textContent = '选择JSON文件或拖放到此处';
                }
            })
            .catch(error => {
                showError(errorAlert, `<i class="bi bi-exclamation-triangle"></i> 上传失败: ${error.message}`);
            })
            .finally(() => {
                // 恢复按钮状态
                submitBtn.disabled = false;
                submitBtn.innerHTML = originalBtnText;
            });
        });
    }
    
    // 上传文件夹中的JSON文件
    const uploadDirectoryForm = document.getElementById('uploadDirectoryForm');
    if (uploadDirectoryForm) {
        uploadDirectoryForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const directoryInput = document.getElementById('jsonDirectory');
            const keywordsInput = document.getElementById('directoryKeywords');
            const successAlert = document.getElementById('directoryUploadSuccess');
            const errorAlert = document.getElementById('directoryUploadError');
            
            if (!directoryInput.files.length) {
                showError(errorAlert, '<i class="bi bi-exclamation-triangle"></i> 请选择一个文件夹');
                return;
            }
            
            // 筛选出所有JSON文件
            const jsonFiles = Array.from(directoryInput.files).filter(file => file.name.endsWith('.json'));
            
            if (jsonFiles.length === 0) {
                showError(errorAlert, '<i class="bi bi-exclamation-triangle"></i> 所选文件夹中没有JSON文件');
                return;
            }
            
            // 显示上传中状态
            const submitBtn = uploadDirectoryForm.querySelector('button[type="submit"]');
            const originalBtnText = submitBtn.innerHTML;
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> 上传中...';
            
            const formData = new FormData();
            
            // 添加所有JSON文件
            jsonFiles.forEach(file => {
                formData.append('files', file);
            });
            
            formData.append('keywords', keywordsInput.value);  // 变量名保持不变，但实际是备注
            
            // 显示上传进度信息
            console.log(`准备上传 ${jsonFiles.length} 个JSON文件`);
            
            fetch('/upload-directory/', {
                method: 'POST',
                body: formData
            })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(data => {
                        console.error('服务器返回错误:', data);
                        throw new Error(data.detail || '上传文件夹失败');
                    });
                }
                return response.json();
            })
            .then(data => {
                console.log('上传成功:', data);
                showSuccess(successAlert, `<i class="bi bi-check-circle"></i> ${data.message}`);
                uploadDirectoryForm.reset();
                // 重置文件上传区域的文本
                const fileUploadArea = uploadDirectoryForm.querySelector('.file-upload-area p');
                if (fileUploadArea) {
                    fileUploadArea.textContent = '选择文件夹';
                }
            })
            .catch(error => {
                console.error('上传错误:', error);
                showError(errorAlert, `<i class="bi bi-exclamation-triangle"></i> 上传失败: ${error.message}`);
            })
            .finally(() => {
                // 恢复按钮状态
                submitBtn.disabled = false;
                submitBtn.innerHTML = originalBtnText;
            });
        });
    }
    
    // 上传历史错题文件
    const uploadHistoryForm = document.getElementById('uploadHistoryForm');
    if (uploadHistoryForm) {
        uploadHistoryForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const subjectSelect = document.getElementById('historySubject');
            const keywordsInput = document.getElementById('historyKeywords');
            const successAlert = document.getElementById('historyUploadSuccess');
            const errorAlert = document.getElementById('historyUploadError');
            
            // 显示上传中状态
            const submitBtn = uploadHistoryForm.querySelector('button[type="submit"]');
            const originalBtnText = submitBtn.innerHTML;
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> 上传中...';
            
            const formData = new FormData();
            formData.append('subject', subjectSelect.value);
            formData.append('keywords', keywordsInput.value);
            
            fetch('/upload-history/', {
                method: 'POST',
                body: formData
            })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(data => {
                        throw new Error(data.detail || '上传历史错题失败');
                    });
                }
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    showSuccess(successAlert, `<i class="bi bi-check-circle"></i> ${data.message}`);
                    uploadHistoryForm.reset();
                } else {
                    showError(errorAlert, `<i class="bi bi-exclamation-triangle"></i> ${data.message}`);
                }
            })
            .catch(error => {
                showError(errorAlert, `<i class="bi bi-exclamation-triangle"></i> 上传失败: ${error.message}`);
            })
            .finally(() => {
                // 恢复按钮状态
                submitBtn.disabled = false;
                submitBtn.innerHTML = originalBtnText;
            });
        });
    }
    
    // 搜索文档
    const searchForm = document.getElementById('searchForm');
    if (searchForm) {
        searchForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const keyword = document.getElementById('searchKeyword').value;
            const limit = document.getElementById('searchLimit').value;
            const searchResults = document.getElementById('searchResults');
            const searchLoading = document.getElementById('searchLoading');
            
            if (!keyword) {
                return;
            }
            
            // 显示加载中
            searchLoading.style.display = 'block';
            searchResults.innerHTML = '';
            
            // 构建表单数据
            const formData = new FormData();
            formData.append('keyword', keyword);
            formData.append('limit', limit);
            
            fetch('/api/search/', {
                method: 'POST',
                body: formData
            })
                .then(response => {
                    if (!response.ok) {
                        throw new Error('搜索请求失败');
                    }
                    return response.json();
                })
                .then(data => {
                    // 隐藏加载中
                    searchLoading.style.display = 'none';
                    // 使用新函数显示结果
                    displaySearchResults(data);
                })
                .catch(error => {
                    console.error('搜索错误:', error);
                    searchLoading.style.display = 'none';
                    searchResults.innerHTML = `
                        <div class="alert alert-danger">
                            <i class="bi bi-exclamation-triangle"></i> 搜索失败: ${error.message}
                        </div>
                    `;
                });
        });
    }
    
    // 加载所有文档
    const loadAllDocuments = document.getElementById('loadAllDocuments');
    if (loadAllDocuments) {
        loadAllDocuments.addEventListener('click', function() {
            getAllDocuments();
        });
        
        // 初始加载
        getAllDocuments();
    }
});

// 加载科目列表
function loadSubjects() {
    const historySubject = document.getElementById('historySubject');
    if (!historySubject) return;
    
    fetch('/subjects/')
        .then(response => {
            if (!response.ok) {
                throw new Error('获取科目列表失败');
            }
            return response.json();
        })
        .then(data => {
            if (data.subjects && data.subjects.length > 0) {
                // 保留第一个"全部科目"选项
                const defaultOption = historySubject.options[0];
                historySubject.innerHTML = '';
                historySubject.appendChild(defaultOption);
                
                // 添加科目选项
                data.subjects.forEach(subject => {
                    const option = document.createElement('option');
                    option.value = subject.id;
                    option.textContent = subject.name;
                    historySubject.appendChild(option);
                });
            }
        })
        .catch(error => {
            console.error('加载科目失败:', error);
        });
}

// 获取所有文档
function getAllDocuments() {
    const allDocuments = document.getElementById('allDocuments');
    const loadingElement = document.getElementById('allDocsLoading');
    
    if (!allDocuments || !loadingElement) return;
    
    // 显示加载中
    loadingElement.style.display = 'block';
    allDocuments.innerHTML = '';
    
    fetch('/documents/')
        .then(response => {
            if (!response.ok) {
                throw new Error('获取文档列表失败');
            }
            return response.json();
        })
        .then(data => {
            // 隐藏加载中
            loadingElement.style.display = 'none';
            
            if (!data.documents || data.documents.length === 0) {
                allDocuments.innerHTML = `
                    <div class="empty-state">
                        <i class="bi bi-folder"></i>
                        <p>没有找到任何文档</p>
                    </div>
                `;
                return;
            }
            
            // 在显示之前处理文档数据，确保所有必需字段都存在
            const processedDocuments = data.documents.map(doc => {
                // 确保所有需要的字段都有默认值，但不添加"未知大小"和"无预览内容"
                return {
                    id: doc.id || doc.file_name || "unknown",
                    filename: doc.filename || doc.file_name || "未知文件名",
                    file_name: doc.file_name || doc.filename || "未知文件名",
                    subject: doc.subject || "",
                    size: doc.size || null,
                    preview: doc.preview || "",
                    created: doc.created || null,
                    content: doc.content || null
                };
            });
            
            // 显示所有文档
            const documentsHTML = processedDocuments.map(doc => {
                return createDocumentCard(doc);
            }).join('');
            
            allDocuments.innerHTML = `
                <div class="row">
                    ${documentsHTML}
                </div>
            `;
        })
        .catch(error => {
            console.error('获取文档失败:', error);
            loadingElement.style.display = 'none';
            allDocuments.innerHTML = `
                <div class="alert alert-danger">
                    <i class="bi bi-exclamation-triangle"></i> 获取文档失败: ${error.message}
                </div>
            `;
        });
}

// 创建文档卡片
function createDocumentCard(doc) {
    // 日期处理 - 如果没有创建时间或时间无效，显示"未知日期"
    let dateStr = "未知日期";
    try {
        if (doc.created) {
            const date = new Date(doc.created * 1000);
            if (!isNaN(date.getTime())) {
                dateStr = date.toLocaleString();
            }
        }
    } catch (e) {
        console.warn("日期格式化错误:", e);
    }
    
    // 文件大小处理 - 如果没有尺寸数据，不显示大小标签
    let sizeStr = "";
    let sizeDisplay = "";
    try {
        if (doc.size && !isNaN(doc.size)) {
            sizeStr = formatFileSize(doc.size);
            sizeDisplay = `<span class="badge">${sizeStr}</span>`;
        }
    } catch (e) {
        console.warn("大小格式化错误:", e);
    }
    
    // 文件名处理 - 确保始终有值
    const filename = doc.filename || doc.file_name || "未知文件名";
    
    // ID处理 - 确保总是有一个ID可以用于链接
    const id = doc.id || (doc.file_name ? doc.file_name : filename);
    
    // 学科展示
    const subject = doc.subject ? `<span class="badge me-2">${doc.subject}</span>` : '';
    
    // 预览内容处理 - 如果没有预览内容，则不显示预览部分
    let preview = '';
    if (doc.preview) {
        preview = `<p class="card-text">${doc.preview}</p>`;
    } else if (doc.content) {
        // 如果有content但没有preview，从content生成预览
        try {
            let previewText = '';
            if (Array.isArray(doc.content)) {
                if (doc.content.length > 0 && typeof doc.content[0] === 'object') {
                    const firstItem = doc.content[0];
                    previewText = firstItem.content || firstItem.question || JSON.stringify(firstItem).substring(0, 100) + '...';
                } else {
                    previewText = JSON.stringify(doc.content).substring(0, 100) + '...';
                }
            } else if (typeof doc.content === 'object') {
                previewText = JSON.stringify(doc.content).substring(0, 100) + '...';
            } else {
                previewText = String(doc.content).substring(0, 100) + '...';
            }
            
            if (previewText.trim()) {
                preview = `<p class="card-text">${previewText}</p>`;
            }
        } catch (e) {
            console.warn("生成预览内容错误:", e);
        }
    }
    
    return `
        <div class="col-md-6 mb-4">
            <div class="card document-card">
                <div class="card-header">
                    <div class="d-flex justify-content-between align-items-center">
                        <h5 class="mb-0">文档 ${filename}</h5>
                        ${sizeDisplay}
                    </div>
                </div>
                <div class="card-body">
                    <div class="document-meta">
                        <span><i class="bi bi-calendar"></i> ${dateStr}</span>
                        ${subject}
                    </div>
                    ${preview}
                    <a href="/document/${id}" class="btn btn-outline-primary btn-sm" target="_blank">
                        <i class="bi bi-eye"></i> 查看文档
                    </a>
                </div>
            </div>
        </div>
    `;
}

// 格式化文件大小
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// 显示成功消息
function showSuccess(element, message) {
    if (element) {
        element.innerHTML = message;
        element.style.display = 'block';
        setTimeout(() => {
            element.style.display = 'none';
        }, 5000);
    }
}

// 显示错误消息
function showError(element, message) {
    if (element) {
        element.innerHTML = message;
        element.style.display = 'block';
        setTimeout(() => {
            element.style.display = 'none';
        }, 5000);
    }
}

// 显示搜索结果的函数
function displaySearchResults(data) {
    const searchResults = document.getElementById('searchResults');
    
    if (!searchResults) return;
    
    if (!data.results || data.results.length === 0) {
        searchResults.innerHTML = `
            <div class="empty-state">
                <i class="bi bi-search"></i>
                <p>没有找到匹配的文档</p>
            </div>
        `;
        return;
    }
    
    // 在显示之前处理文档数据，确保所有必需字段都存在
    const processedResults = data.results.map(doc => {
        // 确保所有需要的字段都有默认值，但不添加"未知大小"和"无预览内容"
        return {
            id: doc.id || doc.file_name || "unknown",
            filename: doc.filename || doc.file_name || "未知文件名",
            file_name: doc.file_name || doc.filename || "未知文件名",
            subject: doc.subject || "",
            size: doc.size || null,
            preview: doc.preview || "",
            created: doc.created || null,
            content: doc.content || null
        };
    });
    
    // 显示搜索结果
    const resultsHTML = processedResults.map(doc => {
        return createDocumentCard(doc);
    }).join('');
    
    searchResults.innerHTML = `
        <h5 class="mb-3">找到 ${data.results.length} 个匹配的文档</h5>
        <div class="row">
            ${resultsHTML}
        </div>
    `;
} 