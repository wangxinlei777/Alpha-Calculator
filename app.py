import os, sys
# 【补丁】针对 Anaconda 环境的手动路径注入，解决 DLL load failed 问题
conda_env = r"H:\Anaconda\Anaconda\envs\py3.8"
if os.path.exists(conda_env):
    os.environ['PATH'] = os.path.join(conda_env, 'Library', 'bin') + os.pathsep + os.environ['PATH']
    if hasattr(os, 'add_dll_directory'):
        try:
            os.add_dll_directory(os.path.join(conda_env, 'Library', 'bin'))
        except:
            pass
from flask import (
    Flask, render_template, request, send_from_directory,
    send_file, jsonify, session, redirect, url_for, abort
)
import pandas as pd
import numpy as np
from scipy.stats import norm
import math
# import xlrd  # 暂不用
from werkzeug.utils import secure_filename

# 初始化
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'outputs'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 最大文件16MB

os.makedirs('uploads', exist_ok=True)
os.makedirs('outputs', exist_ok=True)

import json, io, hashlib, hmac, secrets
from functools import wraps
from datetime import datetime

# 文件路径配置
OVERRIDES_FILE = 'overrides.json'
HISTORY_FILE = 'history.json'
LAST_RESULT_FILE = 'last_result.json'
USERS_FILE = 'users.json'
AUDIT_FILE = 'audit.json'
BACKUP_FOLDER = 'backups'

os.makedirs(BACKUP_FOLDER, exist_ok=True)

# 会话密钥（软著演示环境固定值，实际部署建议修改）
app.secret_key = 'jp-points-decision-2026' + hashlib.md5(str(os.getpid()).encode()).hexdigest()

# 默认账号在首次启动时自动创建：admin / admin123


def load_json_file(path, default):
    """通用 JSON 读取，文件缺失或损坏时返回默认值"""
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            # print(f"[debug] json load failed: {path}")
            pass
    return default


def save_json_file(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4, default=_json_default)


def load_overrides():
    if os.path.exists(OVERRIDES_FILE):
        with open(OVERRIDES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_overrides(overrides):
    with open(OVERRIDES_FILE, 'w', encoding='utf-8') as f:
        json.dump(overrides, f, ensure_ascii=False, indent=4)


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'records': []}


def _json_default(o):
    if hasattr(o, 'item'):
        return o.item()
    return float(o)


def save_history(hist):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(hist, f, ensure_ascii=False, indent=2, default=_json_default)


def load_last_result():
    # TODO: 要不要加个缓存？先不动
    if os.path.exists(LAST_RESULT_FILE):
        with open(LAST_RESULT_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def save_last_result(data):
    with open(LAST_RESULT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=_json_default)


# ====================== 用户 / 审计 数据管理 ======================

def load_users():
    return load_json_file(USERS_FILE, {})


def save_users(users):
    save_json_file(USERS_FILE, users)


def load_audit():
    return load_json_file(AUDIT_FILE, {'logs': []})


def save_audit(data):
    save_json_file(AUDIT_FILE, data)


def add_audit(action, detail='', **extra):
    """记录一条操作日志；异常时静默失败，不影响主流程"""
    try:
        data = load_audit()
        entry = {
            'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'user': session.get('username', '匿名'),
            'action': action,
            'detail': detail,
            'ip': request.remote_addr or '',
        }
        entry.update(extra)
        data['logs'].append(entry)
        if len(data['logs']) > 3000:
            data['logs'] = data['logs'][-3000:]
        save_audit(data)
    except:
        pass  # 审计失败不影响主流程


# ====================== 认证与权限（B5） ======================

def hash_password(pw, salt):
    return hashlib.sha256((salt + pw).encode('utf-8')).hexdigest()


def verify_login(username, password):
    users = load_users()
    u = users.get(username)
    if not u or not password:
        return None
    if hmac.compare_digest(str(u.get('hash', '')), hash_password(password, str(u.get('salt', '')))):
        return u
    return None


def ensure_default_admin():
    """首次启动时创建默认管理员账号 admin/admin123。"""
    users = load_users()
    if 'admin' not in users:
        salt = secrets.token_hex(8)
        users['admin'] = {
            'display_name': '系统管理员',
            'role': 'admin',
            'salt': salt,
            'hash': hash_password('admin123', salt),
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        save_users(users)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            if request.path.startswith('/api/'):
                return jsonify({'status': 'error', 'message': '未登录或会话已过期'}), 401
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapper


def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if session.get('role') not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


@app.before_request
def before_request_check_login():
    p = request.path
    if p in ('/login',) or p.startswith('/static/'):
        return None
    if not session.get('user_id'):
        if p.startswith('/api/'):
            return jsonify({'status': 'error', 'message': '未登录或会话已过期'}), 401
        return redirect(url_for('login'))
    return None


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return redirect('/')
    err = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        u = verify_login(username, password)
        if u:
            session.permanent = True
            session['user_id'] = username
            session['username'] = username
            session['role'] = u.get('role', 'viewer')
            session['display_name'] = u.get('display_name', username)
            add_audit('LOGIN', f'用户登录成功：{username}', username=username)
            nxt = request.args.get('next') or '/'
            if not (nxt.startswith('/') and not nxt.startswith('//')):
                nxt = '/'
            return redirect(nxt)
        add_audit('LOGIN_FAIL', f'登录失败尝试：{username}', username=username)
        err = '用户名或密码错误'
    return render_template('login.html', error=err)


@app.route('/logout')
def logout():
    username = session.get('username', '')
    add_audit('LOGOUT', f'用户退出：{username}', username=username)
    session.clear()
    return redirect(url_for('login'))


@app.route('/api/me')
@login_required
def api_me():
    return jsonify({
        'username': session.get('username'),
        'display_name': session.get('display_name'),
        'role': session.get('role'),
    })


@app.route('/api/users')
@login_required
@role_required('admin')
def api_users():
    users = load_users()
    out = []
    for name, u in users.items():
        out.append({
            'username': name,
            'display_name': u.get('display_name', name),
            'role': u.get('role', 'viewer'),
            'created_at': u.get('created_at', ''),
        })
    return jsonify({'users': sorted(out, key=lambda x: x['username'])})


@app.route('/api/users', methods=['POST'])
@login_required
@role_required('admin')
def api_user_create():
    data = request.json or {}
    username = str(data.get('username', '')).strip()
    password = str(data.get('password', ''))
    role = data.get('role', 'viewer')
    display_name = str(data.get('display_name', '')).strip() or username
    if not username or len(password) < 6:
        return jsonify({'status': 'error', 'message': '用户名不能为空，密码不少于6位'}), 400
    if role not in ('admin', 'operator', 'viewer'):
        return jsonify({'status': 'error', 'message': '角色无效'}), 400
    users = load_users()
    if username in users:
        return jsonify({'status': 'error', 'message': '用户已存在'}), 400
    salt = secrets.token_hex(8)
    users[username] = {
        'display_name': display_name,
        'role': role,
        'salt': salt,
        'hash': hash_password(password, salt),
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    save_users(users)
    add_audit('USER_CREATE', f'新增用户：{username}（角色：{role}）', username=username)
    return jsonify({'status': 'success'})


@app.route('/api/users/<path:username>/password', methods=['POST'])
@login_required
@role_required('admin')
def api_user_password(username):
    data = request.json or {}
    password = str(data.get('password', ''))
    if len(password) < 6:
        return jsonify({'status': 'error', 'message': '密码不少于6位'}), 400
    users = load_users()
    if username not in users:
        return jsonify({'status': 'error', 'message': '用户不存在'}), 404
    users[username]['salt'] = secrets.token_hex(8)
    users[username]['hash'] = hash_password(password, users[username]['salt'])
    save_users(users)
    add_audit('USER_PASSWORD', f'重置用户密码：{username}', username=username)
    return jsonify({'status': 'success'})


@app.route('/api/users/<path:username>', methods=['DELETE'])
@login_required
@role_required('admin')
def api_user_delete(username):
    if username == session.get('user_id'):
        return jsonify({'status': 'error', 'message': '不能删除当前登录账号'}), 400
    users = load_users()
    if username not in users:
        return jsonify({'status': 'error', 'message': '用户不存在'}), 404
    if users[username].get('role') == 'admin' and sum(1 for u in users.values() if u.get('role') == 'admin') <= 1:
        return jsonify({'status': 'error', 'message': '系统至少保留一个管理员账号'}), 400
    del users[username]
    save_users(users)
    add_audit('USER_DELETE', f'删除用户：{username}', username=username)
    return jsonify({'status': 'success'})


# ====================== 操作审计（B6） ======================

@app.route('/api/audit')
@login_required
def api_audit():
    logs = load_audit()['logs']
    user = request.args.get('user', '').strip()
    action = request.args.get('action', '').strip()
    page = max(1, int(request.args.get('page', 1)))
    per_page = int(request.args.get('per_page', 30))
    if user:
        logs = [x for x in logs if user in (x.get('user') or '')]
    if action:
        logs = [x for x in logs if action == x.get('action')]
    logs = list(reversed(logs))
    total = len(logs)
    start = (page - 1) * per_page
    items = logs[start:start + per_page]
    return jsonify({'total': total, 'page': page, 'per_page': per_page, 'logs': items,
                    'actions': sorted({x.get('action') for x in load_audit()['logs']})})


@app.route('/api/audit', methods=['DELETE'])
@login_required
@role_required('admin')
def api_audit_clear():
    save_audit({'logs': []})
    add_audit('AUDIT_CLEAR', '清空操作日志')
    return jsonify({'status': 'success'})


def calculate_all(df, global_params, overrides, selected_names=None):
    MAX_POINT = 100

    # 确定哪些行被选中（用于统计基准和积分池计算）
    if selected_names is not None:
        df['is_selected_in_pool'] = df['卷烟规格'].isin(list(selected_names))
    elif '选品列表' in df.columns:
        df['is_selected_in_pool'] = df['选品列表'] == 1
    else:
        df['is_selected_in_pool'] = True

    # 定义单个品规的计算逻辑
    def calc_row(row):
        name = row['卷烟规格']
        # 优先使用个性化参数，否则使用全局参数
        p = overrides.get(name, global_params)
        is_overridden = name in overrides

        # 1. 盈利因子
        f_profit_book_final = row['F_profit_book'] ** p['K_BOOK_PROFIT']
        f_profit_sale_final = row['F_profit_sale'] ** p['K_SALE_PROFIT']

        # 2. 活跃度因子
        f_active_book_final = row['F_active_book'] ** p['K_BOOK_ACTIVE']
        f_active_sale_final = row['F_active_sale'] ** p['K_SALE_ACTIVE']

        # 3. 库存因子
        f_stock_book_final = row['F_stock_book'] ** p['K_BOOK_STOCK']
        f_stock_sale_final = row['F_stock_sale'] ** p['K_SALE_STOCK']

        # 4. 品牌因子
        f_brand_book_final = row['F_brand_book'] ** p['K_BOOK_BRAND']
        f_brand_sale_final = row['F_brand_sale'] ** p['K_SALE_BRAND']

        # 5. 积分计算
        book_p = p['B_BOOK'] * f_profit_book_final * f_active_book_final * f_stock_book_final * f_brand_book_final
        sale_p = p['B_SALE'] * f_profit_sale_final * f_active_sale_final * f_stock_sale_final * f_brand_sale_final
        
        final_book = math.ceil(book_p) if book_p <= MAX_POINT else MAX_POINT
        final_sale = math.ceil(sale_p) if sale_p <= MAX_POINT else MAX_POINT

        # 因子链式拆解：基准分依次乘以各因子，逐段贡献清晰可解释
        def chain_parts(base, fp, fa, fs, fb, raw_score, final_score):
            s_p = base * fp
            s_a = s_p * fa
            s_s = s_a * fs
            s_b = s_s * fb
            return {
                'base': round(base, 4),
                'profit': round(s_p - base, 4),
                'active': round(s_a - s_p, 4),
                'stock': round(s_s - s_a, 4),
                'brand': round(s_b - s_s, 4),
                'raw': round(raw_score, 4),
                'final': final_score,
                'factors': {
                    'profit': round(fp, 4), 'active': round(fa, 4),
                    'stock': round(fs, 4), 'brand': round(fb, 4),
                },
            }

        breakdown = {
            'book': chain_parts(p['B_BOOK'], f_profit_book_final, f_active_book_final,
                                f_stock_book_final, f_brand_book_final, book_p, final_book),
            'sale': chain_parts(p['B_SALE'], f_profit_sale_final, f_active_sale_final,
                                f_stock_sale_final, f_brand_sale_final, sale_p, final_sale),
        }

        return pd.Series({
            '最终预订积分': final_book,
            '最终销售积分': final_sale,
            'is_overridden': is_overridden,
            'used_params': json.dumps(p),
            'breakdown': json.dumps(breakdown, ensure_ascii=False),
        })

    # --- 预先计算全局通用的因子 ---
    df['单条盈利M'] = df['平均市场价'] - df['批发价']
    mu = df['单条盈利M'].mean()
    sigma = df['单条盈利M'].std()
    df['标准分Z'] = (df['单条盈利M'] - mu) / sigma
    df['分位值P'] = norm.cdf(df['标准分Z'])
    df['F_profit_book'] = 0.5 + 1.5 * df['分位值P']
    df['F_profit_sale'] = 0.5 + 1.5 * (1 - df['分位值P'])

    selected_df_active = df[df['is_selected_in_pool'] == True]
    mu_R = selected_df_active['预订率R'].mean() if len(selected_df_active) > 0 else df['预订率R'].mean()
    df['相对热度X'] = df['预订率R'] / mu_R
    df['F_active_book'] = 0.5 + 1.5 / (1 + np.exp(-(df['相对热度X'] - 1)))
    df['F_active_sale'] = 1 / df['F_active_book']

    df['F_stock_raw'] = 0.5 + 1.5 / (1 + np.exp(-(df['存销比T'] - 1)))
    df['F_stock_book'] = 1 / df['F_stock_raw']
    df['F_stock_sale'] = df['F_stock_raw']

    df['F_brand_raw'] = (df['Bbase'] * df['Bgoal']).clip(0.5, 2.0)
    df['F_brand_book'] = df['F_brand_raw']
    df['F_brand_sale'] = 1 / df['F_brand_raw']

    # 应用行级个性化权重
    res_cols = df.apply(calc_row, axis=1)
    df = pd.concat([df, res_cols], axis=1)

    # 总积分汇总
    df['上半年条数'] = pd.to_numeric(df['上半年条数'], errors='coerce').fillna(0)
    df['总预定积分'] = df['上半年条数'] * df['最终预订积分']
    df['总销售积分'] = df['上半年条数'] * df['最终销售积分']
    df['总积分数'] = df['总销售积分'] - df['总预定积分']

    # 积分池计算
    selected_df = df[df['is_selected_in_pool'] == True].copy()
    pool_data = {
        'pool_book': round(selected_df['总预定积分'].sum(), 2),
        'pool_sale': round(selected_df['总销售积分'].sum(), 2),
        'pool_total': round(selected_df['总销售积分'].sum() - selected_df['总预定积分'].sum(), 2)
    }

    return df, pool_data


# ====================== 数据质量体检（A4） ======================

REQUIRED_COLS = ['代码', '卷烟规格', '批发价', '平均市场价', '预订率R', '存销比T', 'Bbase', 'Bgoal', '上半年箱数']
NUMERIC_COLS = ['批发价', '平均市场价', '预订率R', '存销比T', 'Bbase', 'Bgoal', '上半年箱数']


def audit_dataframe(df):
    """上传数据质量体检，返回 (清洗后的DataFrame, 体检报告)"""
    report = {'status': 'ok', 'counts': {}, 'messages': []}
    if df is None or len(df) == 0:
        return df, {'status': 'error', 'counts': {'rows': 0},
                    'messages': [{'level': 'error', 'text': '数据表为空，没有可计算的行'}]}

    report['counts']['rows'] = len(df)

    # 空白行
    blank_rows = int(df.isna().all(axis=1).sum())
    report['counts']['blank_rows'] = blank_rows
    if blank_rows:
        report['messages'].append({'level': 'warn',
                                   'text': f'检测到 {blank_rows} 行完全空白的记录，已剔除，不参与计算。'})
        df = df[~df.isna().all(axis=1)]

    # 必填列
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    report['counts']['missing_cols'] = missing
    if missing:
        report['status'] = 'error'
        report['messages'].append({'level': 'error',
                                   'text': '缺少必填列：' + '、'.join(missing)})
        report['messages'].append({'level': 'error',
                                   'text': '请按标准模板整理数据后重新上传（可先下载模板核对列名）。'})
        return df, report

    # 重复品规/代码
    dup_spec = int(df['卷烟规格'].duplicated().sum())
    dup_code = int(df['代码'].duplicated().sum())
    report['counts']['duplicate_spec'] = dup_spec
    report['counts']['duplicate_code'] = dup_code
    if dup_spec:
        ex = df[df['卷烟规格'].duplicated()]['卷烟规格'].head(5).tolist()
        report['messages'].append({'level': 'warn',
                                   'text': f'存在 {dup_spec} 个重复品规名称：' + '、'.join(map(str, ex)) + ' 等（将按首个取值计算）。'})
    if dup_code:
        report['messages'].append({'level': 'warn',
                                   'text': f'存在 {dup_code} 个重复品规代码，建议核对来源数据。'})

    # 数值列非数值/缺失
    non_numeric = 0
    for col in NUMERIC_COLS:
        conv = pd.to_numeric(df[col], errors='coerce')
        bad = int(conv.isna().sum()) - int(df[col].isna().sum())
        miss = int(df[col].isna().sum())
        non_numeric += bad
        if bad:
            report['messages'].append({'level': 'warn',
                                       'text': f'列【{col}】存在 {bad} 个无法识别的数值，已按缺失处理。'})
        if miss:
            report['messages'].append({'level': 'warn',
                                       'text': f'列【{col}】存在 {miss} 个空值。'})
    report['counts']['non_numeric'] = non_numeric

    # 价格倒挂：批发价高于市场价
    wp = pd.to_numeric(df['批发价'], errors='coerce')
    mp = pd.to_numeric(df['平均市场价'], errors='coerce')
    inv = (wp > mp) & mp.notna()
    report['counts']['price_inverted'] = int(inv.sum())
    if inv.sum():
        ex = df.loc[inv, '卷烟规格'].head(5).tolist()
        report['messages'].append({'level': 'warn',
                                   'text': f'有 {int(inv.sum())} 个品规批发价高于市场均价（单条盈利为负）：' + '、'.join(map(str, ex)) + ' 等'})

    # 比率/数量异常
    r_col = pd.to_numeric(df['预订率R'], errors='coerce')
    t_col = pd.to_numeric(df['存销比T'], errors='coerce')
    box_col = pd.to_numeric(df['上半年箱数'], errors='coerce')
    r_bad = int((((r_col < 0) | (r_col > 1)) & r_col.notna()).sum())
    t_bad = int(((t_col <= 0) & t_col.notna()).sum())
    box_bad = int(((box_col < 0) & box_col.notna()).sum())
    report['counts']['abnormal'] = r_bad + t_bad + box_bad
    if r_bad:
        report['messages'].append({'level': 'warn', 'text': f'有 {r_bad} 个品规预订率R超出[0,1]区间。'})
    if t_bad:
        report['messages'].append({'level': 'warn', 'text': f'有 {t_bad} 个品规存销比T≤0。'})
    if box_bad:
        report['messages'].append({'level': 'warn', 'text': f'有 {box_bad} 个品规上半年箱数<0。'})

    if '选品列表' in df.columns:
        report['counts']['selected'] = int((df['选品列表'] == 1).sum())
    else:
        report['counts']['selected'] = None

    if report['messages']:
        report['status'] = 'warn'
    return df, report


@app.route('/', methods=['GET', 'POST'])
def index():
    result_data = None
    download_filename = None
    pool_data = None
    ranking_top3 = None
    ranking_bottom3 = None
    audit_report = None
    params = {}
    original_filename = request.form.get('original_filename')
    overrides = load_overrides()
    
    # 获取显示模式及选中的品规列表
    display_mode = request.form.get('display_mode', 'all')
    selected_items = request.form.getlist('selected_items')

    if request.method == 'POST':
        try:
            params = {
                'B_BOOK': float(request.form.get('B_BOOK', 6)),
                'B_SALE': float(request.form.get('B_SALE', 3)),
                'K_BOOK_PROFIT': float(request.form.get('K_BOOK_PROFIT', 3)),
                'K_SALE_PROFIT': float(request.form.get('K_SALE_PROFIT', 3)),
                'K_BOOK_ACTIVE': float(request.form.get('K_BOOK_ACTIVE', 0.3)),
                'K_SALE_ACTIVE': float(request.form.get('K_SALE_ACTIVE', 0.3)),
                'K_BOOK_STOCK': float(request.form.get('K_BOOK_STOCK', 0.3)),
                'K_SALE_STOCK': float(request.form.get('K_SALE_STOCK', 0.3)),
                'K_BOOK_BRAND': float(request.form.get('K_BOOK_BRAND', 0.3)),
                'K_SALE_BRAND': float(request.form.get('K_SALE_BRAND', 0.3))
            }
        except ValueError:
            add_audit('COMPUTE_FAIL', '参数解析失败：存在非数值参数')
            params = dict(DEFAULT_PARAMS)

        viewer_blocked = session.get('role') == 'viewer'
        if viewer_blocked:
            add_audit('COMPUTE_BLOCKED', '只读账号尝试执行计算，已拦截')

        file = request.files.get('excel_file')
        target_file_path = None
        
        if file and file.filename != '':
            # 保留原始文件名（兼容中文名），仅剔除路径部分并确保扩展名存在
            original_filename = os.path.basename(file.filename)
            if not os.path.splitext(original_filename)[1]:
                original_filename += '.xlsx'
            target_file_path = os.path.join(app.config['UPLOAD_FOLDER'], original_filename)
            file.save(target_file_path)
            # 首次上传文件时，清空之前的手动选品
            selected_items = None
        elif original_filename:
            temp_path = os.path.join(app.config['UPLOAD_FOLDER'], original_filename)
            if os.path.exists(temp_path):
                target_file_path = temp_path

        if target_file_path:
            df = pd.read_excel(target_file_path, header=3)
            df.columns = [str(col).strip() for col in df.columns]

            # 数据质量体检
            df, audit_report = audit_dataframe(df)

            if audit_report.get('status') == 'error':
                add_audit('COMPUTE_BLOCKED',
                          f'数据体检未通过，已阻止计算：{original_filename}（' +
                          '；'.join(m['text'] for m in audit_report['messages']) + '）')
            elif viewer_blocked:
                pass  # 只读账号：仅展示体检报告，不执行计算
            else:
                # 传入全局参数字典、个性化配置及手动选品列表
                df_result, pool_data = calculate_all(df, params, overrides, selected_names=selected_items)

                download_filename = f"积分结果_{original_filename}"
                output_path = os.path.join(app.config['OUTPUT_FOLDER'], download_filename)
                df_result.to_excel(output_path, index=False)

                result_data = df_result[['卷烟规格','平均市场价','批发价','上半年箱数','最终预订积分','最终销售积分',
                                       '总预定积分','总销售积分','总积分数','is_overridden','used_params','breakdown', 'is_selected_in_pool']].to_dict('records')

                # 缓存本次计算结果，供“历史周期保存”功能使用
                save_last_result({
                    'params': params,
                    'overrides': overrides,
                    'original_filename': original_filename,
                    'selected_items': selected_items if selected_items else df_result['卷烟规格'].tolist(),
                    'pool': pool_data,
                    'items': df_result[['卷烟规格','预订率R','平均市场价','批发价','上半年箱数','箱条数','上半年条数',
                                        'F_profit_book','F_profit_sale',
                                        'F_active_book','F_active_sale',
                                        'F_stock_book','F_stock_sale',
                                        'F_brand_book','F_brand_sale',
                                        '最终预订积分','最终销售积分',
                                        '总预定积分','总销售积分',
                                        'used_params','is_overridden','breakdown','is_selected_in_pool']].to_dict('records')
                })
                add_audit('COMPUTE',
                          f'完成决策计算：{original_filename}，选品 {pool_data["pool_book"]:,.0f} 预订单 / '
                          f'{pool_data["pool_sale"]:,.0f} 销售单，池差额 {pool_data["pool_total"]:+,.0f}，'
                          f'体检状态：{audit_report.get("status", "ok")}')

                # 预订活跃度排行（Top3 / Bottom3），按预订率R排序
                rank_view = df_result[['卷烟规格','预订率R','最终预订积分','最终销售积分']].copy()
                rank_view = rank_view.sort_values('预订率R', ascending=False)
                ranking_top3 = rank_view.head(3).to_dict('records')
                ranking_bottom3 = rank_view.tail(3).to_dict('records')
        else:
            add_audit('COMPUTE_FAIL', '未找到可用的数据文件')

    return render_template('index.html', 
                         result=result_data, 
                         filename=download_filename, 
                         pool=pool_data, 
                         params=params,
                         original_filename=original_filename,
                         display_mode=display_mode,
                         ranking_top3=ranking_top3,
                         ranking_bottom3=ranking_bottom3,
                         audit_report=audit_report,
                         viewer_blocked=viewer_blocked if 'viewer_blocked' in locals() else False,
                         user_info={'username': session.get('username'), 'role': session.get('role'),
                                    'display_name': session.get('display_name')})


@app.route('/api/save_override', methods=['POST'])
def api_save_override():
    data = request.json
    name = data.get('name')
    if not name: return {"status": "error", "message": "Missing name"}, 400
    
    overrides = load_overrides()
    overrides[name] = data['params']
    save_overrides(overrides)
    add_audit('SAVE_OVERRIDE', f'品规【{name}】启用个性化调权')
    return {"status": "success"}


@app.route('/api/reset_override', methods=['POST'])
def api_reset_override():
    name = request.json.get('name')
    overrides = load_overrides()
    if name in overrides:
        del overrides[name]
        save_overrides(overrides)
        add_audit('RESET_OVERRIDE', f'品规【{name}】恢复全局参数')
    return {"status": "success"}

@app.route('/download/<filename>')
def download_file(filename):
    add_audit('EXPORT', f'下载结果报告：{filename}')
    return send_from_directory(app.config['OUTPUT_FOLDER'], filename, as_attachment=True)


@app.route('/api/save_history', methods=['POST'])
def api_save_history():
    data = request.json or {}
    name = (data.get('name') or '').strip()
    last = load_last_result()
    if last is None:
        return {"status": "error", "message": "请先执行一次决策计算，再保存历史周期"}, 400

    hist = load_history()
    # 内容签名去重：同一份计算结果（参数+品规明细）只允许存档一次，防止误触/重复提交
    sig_src = {'params': last.get('params'), 'overrides': last.get('overrides'), 'items': last.get('items')}
    sig = hashlib.md5(json.dumps(sig_src, ensure_ascii=False, default=_json_default).encode('utf-8')).hexdigest()
    for rec in hist['records']:
        if rec.get('signature') == sig:
            return {"status": "success", "duplicate": True,
                    "record": {"id": rec['id'], "name": rec['name'], "created_at": rec['created_at']}}

    records = hist['records']
    new_id = max([r['id'] for r in records], default=0) + 1
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    record = {
        'id': new_id,
        'name': name or now,
        'created_at': now,
        'signature': sig,
        'params': last.get('params'),
        'overrides': last.get('overrides'),
        'original_filename': last.get('original_filename'),
        'selected_items': last.get('selected_items'),
        'pool': last.get('pool'),
        'items': last.get('items', [])
    }
    records.append(record)
    save_history(hist)
    add_audit('SAVE_PERIOD', f'保存历史周期：{record["name"]}（{len(record["items"])} 个品规）')
    return {"status": "success", "record": {"id": record['id'], "name": record['name'], "created_at": record['created_at']}}


@app.route('/api/history')
def api_history():
    return jsonify(load_history())


@app.route('/api/history/<int:rid>', methods=['DELETE'])
def api_history_delete(rid):
    hist = load_history()
    before = len(hist['records'])
    hist['records'] = [r for r in hist['records'] if r['id'] != rid]
    if len(hist['records']) == before:
        return {"status": "error", "message": "记录不存在"}, 404
    save_history(hist)
    add_audit('DELETE_PERIOD', f'删除历史周期 #{rid}')
    return {"status": "success"}


@app.route('/api/history/<int:rid>/rename', methods=['POST'])
def api_history_rename(rid):
    data = request.json or {}
    name = (data.get('name') or '').strip()
    if not name:
        return {"status": "error", "message": "名称不能为空"}, 400
    hist = load_history()
    rec = next((r for r in hist['records'] if r['id'] == rid), None)
    if rec is None:
        return {"status": "error", "message": "记录不存在"}, 404
    rec['name'] = name
    save_history(hist)
    add_audit('RENAME_PERIOD', f'历史周期 #{rid} 重命名为：{name}')
    return {"status": "success"}


@app.route('/api/history/export')
def api_history_export():
    hist = load_history()
    records = sorted(hist.get('records', []), key=lambda r: (r.get('created_at', ''), r.get('id', 0)))
    if not records:
        return {"status": "error", "message": "暂无历史记录"}, 400

    overview_rows = []
    detail_rows = []
    for r in records:
        pool = r.get('pool') or {}
        overview_rows.append({
            '周期ID': r['id'],
            '周期名称': r.get('name', ''),
            '保存时间': r.get('created_at', ''),
            '品规数': len(r.get('items', [])),
            '池总预订积分': pool.get('pool_book'),
            '池总销售积分': pool.get('pool_sale'),
            '池积分差额': pool.get('pool_total'),
        })
        for it in r.get('items', []):
            detail_rows.append({
                '周期ID': r['id'],
                '周期名称': r.get('name', ''),
                '保存时间': r.get('created_at', ''),
                '卷烟规格': it.get('卷烟规格'),
                '预订率R': it.get('预订率R'),
                '最终预订积分': it.get('最终预订积分'),
                '最终销售积分': it.get('最终销售积分'),
                '平均市场价': it.get('平均市场价'),
                '批发价': it.get('批发价'),
                '盈利因子(预订)': it.get('F_profit_book'),
                '活跃因子(预订)': it.get('F_active_book'),
                '库存因子(预订)': it.get('F_stock_book'),
                '品牌因子(预订)': it.get('F_brand_book'),
            })

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        pd.DataFrame(overview_rows).to_excel(writer, sheet_name='周期总览', index=False)
        pd.DataFrame(detail_rows).to_excel(writer, sheet_name='品规明细', index=False)
    buf.seek(0)
    fname = f'历史周期存档_{datetime.now().strftime("%Y%m%d%H%M%S")}.xlsx'
    add_audit('EXPORT_ARCHIVE', f'导出历史存档 Excel（{len(records)} 个周期）')
    return send_file(buf, as_attachment=True, download_name=fname,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ====================== 决策核心算法（供试算/建议复用） ======================

def score_spec_factors(row, params, override):
    """按参数对单个品规重新打分（用于方案试算与投放建议）"""
    p = override or params
    book_p = p['B_BOOK'] * (row['F_profit_book'] ** p['K_BOOK_PROFIT']) * (row['F_active_book'] ** p['K_BOOK_ACTIVE']) \
        * (row['F_stock_book'] ** p['K_BOOK_STOCK']) * (row['F_brand_book'] ** p['K_BOOK_BRAND'])
    sale_p = p['B_SALE'] * (row['F_profit_sale'] ** p['K_SALE_PROFIT']) * (row['F_active_sale'] ** p['K_SALE_ACTIVE']) \
        * (row['F_stock_sale'] ** p['K_SALE_STOCK']) * (row['F_brand_sale'] ** p['K_SALE_BRAND'])
    book = min(math.ceil(book_p), 100)
    sale = min(math.ceil(sale_p), 100)
    return book, sale


def current_items():
    """返回最近一次计算结果的品规明细（含因子与量数据）。"""
    last = load_last_result()
    if not last:
        return None, None, None
    items = last.get('items', [])
    selected = last.get('selected_items') or [x['卷烟规格'] for x in items]
    return last, items, set(selected)


def item_qty(it):
    """从存档条目中提取 箱数/条数/箱条数，兼容旧版存档缺失字段的情况。"""
    tiao = it.get('上半年条数')
    if tiao is None:
        fb = it.get('最终预订积分') or 0
        tiao = (it.get('总预定积分') or 0) / fb if fb else 0
    box = it.get('上半年箱数')
    per_box = it.get('箱条数')
    if box is None and per_box and per_box > 0:
        box = tiao * per_box
    if per_box is None or per_box <= 0:
        per_box = (box / tiao) if tiao else 1
    return {'box': box or 0, 'tiao': tiao or 0, 'per_box': per_box or 1}


def simulate_with_params(params, overrides=None):
    """用给定全局参数 + 当前个性化配置，对最近一次计算结果做整体试算"""
    last, items, selected = current_items()
    if items is None:
        return None
    ov = overrides if overrides is not None else last.get('overrides') or {}
    base = last.get('params') or {}
    rows = []
    pool_book = pool_sale = 0.0
    for it in items:
        name = it['卷烟规格']
        if name not in selected:
            continue
        row = {
            'F_profit_book': it.get('F_profit_book'), 'F_profit_sale': it.get('F_profit_sale'),
            'F_active_book': it.get('F_active_book'), 'F_active_sale': it.get('F_active_sale'),
            'F_stock_book': it.get('F_stock_book'), 'F_stock_sale': it.get('F_stock_sale'),
            'F_brand_book': it.get('F_brand_book'), 'F_brand_sale': it.get('F_brand_sale'),
        }
        p = dict(base)
        p.update(params)
        book, sale = score_spec_factors(row, p, ov.get(name))
        t_book = (item_qty(it)['tiao']) * book
        t_sale = (item_qty(it)['tiao']) * sale
        pool_book += t_book
        pool_sale += t_sale
        rows.append({'卷烟规格': name, 'book': book, 'sale': sale,
                     't_book': round(t_book, 2), 't_sale': round(t_sale, 2)})
    return {
        'pool': {'pool_book': round(pool_book, 2), 'pool_sale': round(pool_sale, 2),
                 'pool_total': round(pool_sale - pool_book, 2)},
        'rows': rows,
    }


# ====================== 参数基准与试算（供投放建议使用） ======================

DEFAULT_PARAMS = {
    'B_BOOK': 6, 'B_SALE': 3,
    'K_BOOK_PROFIT': 3, 'K_SALE_PROFIT': 3,
    'K_BOOK_ACTIVE': 0.3, 'K_SALE_ACTIVE': 0.3,
    'K_BOOK_STOCK': 0.3, 'K_SALE_STOCK': 0.3,
    'K_BOOK_BRAND': 0.3, 'K_SALE_BRAND': 0.3,
}


# ====================== 投放量建议 / 目标差额倒算（A3） ======================

@app.route('/api/suggest/baseline', methods=['POST'])
@login_required
def api_suggest_baseline():
    """目标差额倒算：求解基准预订积分 B_BOOK，使池差额尽量接近目标值。"""
    data = request.json or {}
    target = float(data.get('target', 0) or 0)
    last, items, selected = current_items()
    if items is None:
        return jsonify({'status': 'error', 'message': '请先执行一次决策计算'}), 400
    base = dict(last.get('params') or DEFAULT_PARAMS)
    ov = last.get('overrides') or {}

    def evaluate(b_book):
        p = dict(base)
        p['B_BOOK'] = b_book
        r = simulate_with_params(p, ov)
        return r['pool']['pool_total']

    lo, hi = 0.1, 80.0
    best_b, best_err = base.get('B_BOOK', 6), abs(evaluate(base.get('B_BOOK', 6)) - target)
    for _ in range(40):
        mid = (lo + hi) / 2
        diff = evaluate(mid)
        err = abs(diff - target)
        if err < best_err:
            best_b, best_err = mid, err
        if diff > target:
            lo = mid  # 差额偏大 → 需要加大预订积分（增大 B_BOOK）
        else:
            hi = mid


        # 再精细扫描一次防止二分边界问题
    step = 0.1
    b0 = max(0.1, best_b - 1.0)
    for b in [b0 + i * step for i in range(int(20 / step) + 1)]:
        err = abs(evaluate(b) - target)
        if err < best_err:
            best_b, best_err = b, err

    p = dict(base)
    p['B_BOOK'] = round(best_b, 2)
    r = simulate_with_params(p, ov)
    residual = round(r['pool']['pool_total'] - target, 2)
    add_audit('SUGGEST_BASELINE', f'目标差额 {target:+,.0f} → 建议基准预订积分 {p["B_BOOK"]}（试算差额 {r["pool"]["pool_total"]:+,.0f}，残余 {residual:+,.0f}）')
    return jsonify({
        'status': 'success',
        'b_book': p['B_BOOK'],
        'achieved_diff': r['pool']['pool_total'],
        'residual': residual,
        'pool': r['pool'],
    })


@app.route('/api/suggest/adjust', methods=['POST'])
@login_required
def api_suggest_adjust():
    """分品规投放量调整建议：通过增减选品箱数，把池差额引导到目标值。"""
    data = request.json or {}
    target = float(data.get('target', 0) or 0)
    max_ratio = float(data.get('max_ratio', 0.3) or 0.3)
    last, items, selected = current_items()
    if items is None:
        return jsonify({'status': 'error', 'message': '请先执行一次决策计算'}), 400

    base = dict(last.get('params') or DEFAULT_PARAMS)
    ov = last.get('overrides') or {}
    pool = last.get('pool') or {'pool_total': 0}

    # 当前各选品品规的箱数与积分
    recs = []
    for it in items:
        name = it['卷烟规格']
        if name not in selected:
            continue
        q = item_qty(it)
        box = q['box']
        per_box = q['per_box']
        row = {'F_profit_book': it.get('F_profit_book'), 'F_profit_sale': it.get('F_profit_sale'),
               'F_active_book': it.get('F_active_book'), 'F_active_sale': it.get('F_active_sale'),
               'F_stock_book': it.get('F_stock_book'), 'F_stock_sale': it.get('F_stock_sale'),
               'F_brand_book': it.get('F_brand_book'), 'F_brand_sale': it.get('F_brand_sale')}
        book, _ = score_spec_factors(row, base, ov.get(name))
        recs.append({
            'name': name, 'box': box, 'book': book, 'per_box': per_box,
            'effect_per_box': book / per_box if per_box else book,
            'max_delta': box * max_ratio,
        })
    if not recs:
        return jsonify({'status': 'error', 'message': '当前选品集合为空'}), 400

    gap = pool.get('pool_total', 0) - target  # 差额高于目标 → 需增加预订积分
    direction = 1 if gap > 0 else -1
    need = abs(gap)

    # 按单位箱数影响从大到小依次分配
    recs_sorted = sorted(recs, key=lambda r: -r['effect_per_box'])
    used_delta = {}
    covered = 0.0
    for r in recs_sorted:
        capacity = r['max_delta'] * r['effect_per_box']
        take = min(need - covered, capacity, r['max_delta'] * r['effect_per_box'])
        if take > 0:
            used_delta[r['name']] = {'delta_box': take / r['effect_per_box'], 'take': take}
            covered += take
        if covered >= need:
            break

    rows = []
    for r in recs:
        adj = used_delta.get(r['name'])
        delta_box = direction * (adj['delta_box'] if adj else 0)
        impact = direction * (adj['take'] if adj else 0)
        rows.append({
            'name': r['name'],
            'box': round(r['box'], 2),
            'book': r['book'],
            'delta_box': round(delta_box, 2),
            'suggest_box': round(r['box'] + delta_box, 2),
            'impact': round(impact, 2),
        })

    new_book = last.get('pool', {}).get('pool_book', 0)
    if direction == 1:
        new_book = (last.get('pool', {}).get('pool_book') or 0) + covered
    else:
        new_book = (last.get('pool', {}).get('pool_book') or 0) - covered
    new_diff = (last.get('pool', {}).get('pool_sale') or 0) - new_book

    add_audit('SUGGEST_ADJUST', f'投放量建议：目标差额 {target:+,.0f}，覆盖 {covered:,.0f} 预订积分，投影差额 {new_diff:+,.0f}')
    return jsonify({
        'status': 'success',
        'target': target,
        'direction': direction,
        'need': round(need, 2),
        'covered': round(covered, 2),
        'feasible': covered >= need - 1e-6,
        'new_diff': round(new_diff, 2),
        'rows': rows,
    })


# ====================== 系统备份与恢复（B8） ======================

BACKUP_FILES = ['history.json', 'last_result.json', 'overrides.json']


@app.route('/api/backup', methods=['POST'])
@login_required
@role_required('admin', 'operator')
def api_backup_create():
    """把全部业务数据打包为 zip 供下载。"""
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name in BACKUP_FILES:
            if os.path.exists(name):
                zf.write(name, arcname=name)
    buf.seek(0)
    fname = f'积分系统备份_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'
    add_audit('BACKUP_CREATE', f'创建系统备份包：{fname}')
    return send_file(buf, as_attachment=True, download_name=fname, mimetype='application/zip')


@app.route('/api/restore', methods=['POST'])
@login_required
@role_required('admin')
def api_restore():
    """从备份包恢复数据；恢复前自动生成一份当前数据的备份。"""
    import zipfile
    file = request.files.get('backup_file')
    if not file or file.filename == '':
        return jsonify({'status': 'error', 'message': '请选择备份文件'}), 400

    try:
        zf = zipfile.ZipFile(io.BytesIO(file.read()))
        names = set(zf.namelist())
        missing = [n for n in BACKUP_FILES if n not in names]
        if missing:
            return jsonify({'status': 'error', 'message': '备份包内容不完整，缺少：' + '、'.join(missing)}), 400

        # 恢复前自动备份当前状态
        auto = f'{BACKUP_FOLDER}/自动备份_恢复前_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'
        with zipfile.ZipFile(auto, 'w', zipfile.ZIP_DEFLATED) as ab:
            for name in BACKUP_FILES:
                if os.path.exists(name):
                    ab.write(name, arcname=name)

        for name in BACKUP_FILES:
            with zf.open(name) as src, open(name, 'wb') as dst:
                dst.write(src.read())
        add_audit('RESTORE', f'从备份包恢复数据（已有数据已自动备份至 {auto}）')
        return jsonify({'status': 'success'})
    except zipfile.BadZipFile:
        return jsonify({'status': 'error', 'message': '文件不是有效的备份包'}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'恢复失败：{e}'}), 500


ensure_default_admin()

if __name__ == '__main__':
    app.run(debug=True)