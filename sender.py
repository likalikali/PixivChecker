import time
import json
import os
import requests
import re
from pixivpy3 import AppPixivAPI
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from dotenv import load_dotenv
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
# ================= 加载配置 =================
load_dotenv()

# 1. 基础开关与显示配置
ENABLE_TG = os.getenv("ENABLE_TG", "False").lower() == "false"
ENABLE_EMAIL = os.getenv("ENABLE_EMAIL", "True").lower() == "true"
PREVIEW_LEN = int(os.getenv("PREVIEW_LEN", 200))

# 2. 邮件配置
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.qq.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 465))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
RECEIVER = os.getenv("RECEIVER") or EMAIL_USER

# 3. Pixiv 配置
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
KEYWORDS_STR = os.getenv("SEARCH_KEYWORDS", "")
KEYWORDS = [k.strip() for k in KEYWORDS_STR.split(",") if k.strip()]
SEARCH_TARGET = os.getenv("SEARCH_TARGET", "partial_match_for_tags")

# 4. Telegram 配置
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

# 5. 其他配置

# 默认回溯 1.0 天 (24小时)，配合 hourly 运行，确保不漏抓
MAX_DAYS = float(os.getenv("MAX_DAYS", 1.0))


# ================= 辅助函数 =================

def load_history():
    try:
        res = supabase.table("sent_novels").select("id").execute()
        return [row['id'] for row in res.data]
    except Exception as e:
        print(f"❌ Supabase load 失败: {e}")
        return []


def save_history(history_list):
    try:
        new_ids = set(history_list[-1000:])  # 去重，保留最近1000
        for hid in new_ids:
            supabase.table("sent_novels").upsert({"id": hid}).execute()
        print(f"✅ 已更新 Supabase 历史记录，新增 {len(new_ids)} 条")
    except Exception as e:
        print(f"❌ Supabase save 失败: {e}")


def clean_html(raw_text):
    if not raw_text:
        return "无法获取正文预览"
    cleanr = re.compile('<.*?>')
    text = re.sub(cleanr, '', raw_text)
    text = re.sub(r'\[.*?\]', '', text)
    text = text.replace('\n', ' ').replace('\r', ' ').strip()
    return text[:PREVIEW_LEN] + "..." if len(text) > PREVIEW_LEN else text


def parse_to_beijing_time(time_str):
    try:
        main_time = time_str.split('+')[0]
        dt_jst = datetime.strptime(main_time, "%Y-%m-%dT%H:%M:%S")
        # JST 是 UTC+9，北京时间是 UTC+8，所以减1小时
        dt_beijing = dt_jst - timedelta(hours=1)
        return dt_beijing
    except:
        return None


def send_aggregated_email(novel_items, time_info):
    if not ENABLE_EMAIL or not novel_items: return

    subject = f"Pixiv汇总：发现 {len(novel_items)} 篇新作品 ({time_info['now_date']})"

    html_body = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #333; max-width: 600px; margin: auto;">
        <h2 style="color: #0096fa; margin-bottom: 10px;">Pixiv 关键词监控报告</h2>
        <p style="font-size: 13px; color: #888; margin-top: 0;">
            <b>关键词：</b> {KEYWORDS_STR}<br>
            <b>执行时间：</b> {time_info['exec_time']}<br>
            <b>内容范围：</b> {time_info['range']}
        </p>
        <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
    """

    for i, item in enumerate(novel_items, 1):
        # 构造HTML部分
        html_body += f"""
        <div style="margin-bottom: 30px; border-bottom: 1px dashed #eee; padding-bottom: 20px;">
            <h3 style="margin-bottom: 8px; font-size: 18px;">
                <span style="color: #aaa; font-weight: normal; margin-right: 5px;">#{i}</span>
                <a href="{item['url_web']}" style="color: #333; text-decoration: none;">{item['title']}</a>
            </h3>
            <p style="color: #666; font-size: 13px; margin: 5px 0 15px 0;">
                <!-- 修改：增加了作者主页链接和ID显示 -->
                👤 作者: <a href="{item['author_url']}" style="color: #333; text-decoration: none; font-weight: bold;">{item['author']}</a> <span style="color: #999; font-size: 12px;">(ID: {item['author_id']})</span> 
                &nbsp;|&nbsp; 🕒 发布: {item['pub_date']}
            </p>

            <div style="font-size: 13px; color: #555; background: #f9f9f9; padding: 12px; border-radius: 6px; line-height: 1.6; margin-bottom: 15px;">
                {item['content_preview']}
            </div>

            <!-- 操作区域 -->
            <div style="margin-top: 15px;">
                <div style="background: #f0f4c3; border: 1px solid #dce775; padding: 10px; border-radius: 6px;">
                    <code style="font-size: 12px; font-family: monospace; color: #558b2f; word-break: break-all;">{item['url_pixez']}</code>
                </div>
            </div>
        </div>
        """

    html_body += """
        <div style="text-align: center; margin-top: 40px; font-size: 12px; color: #ccc;">
            Generated by Pixiv-Monitor-Bot
        </div>
    </div>
    """

    message = MIMEText(html_body, 'html', 'utf-8')
    message['From'] = EMAIL_USER
    message['To'] = RECEIVER
    message['Subject'] = Header(subject, 'utf-8')
    try:
        with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, [RECEIVER], message.as_string())
        print(f"✅ [Email] 成功发送序号 1-{len(novel_items)} 的汇总邮件")
    except Exception as e:
        print(f"❌ [Email] 发送失败: {e}")


def send_aggregated_tg(novel_items, time_info):
    if not ENABLE_TG or not novel_items: return

    header = (
        f"<b>📅 Pixiv 实时监控 ({len(novel_items)}篇)</b>\n"
        f"⏱ 扫描时间: <code>{time_info['exec_time']}</code>\n"
        f"⏳ 内容范围: <code>{time_info['range']}</code>\n"
        f"--------------------------------\n\n"
    )
    content = ""
    for i, item in enumerate(novel_items, 1):
        # 修改：增加了作者主页链接和ID显示
        item_str = (
            f"{i}. <b>{item['title']}</b>\n"
            f"👤 作者: <a href='{item['author_url']}'>{item['author']}</a> (<code>{item['author_id']}</code>)\n"
            f"🕒 发布: {item['pub_date']}\n"
            f"🆔 ID: <code>{item['id']}</code> (点击复制)\n"
            f"🔗 <a href='{item['url_web']}'>网页版</a>\n"
            f"🚀 Scheme: <code>{item['url_pixez']}</code>\n\n"
        )
        if len(content + item_str + header) > 4000:
            _post_to_tg(header + content)
            content, header = item_str, ""
        else:
            content += item_str
    _post_to_tg(header + content)


def _post_to_tg(text):
    if not TG_BOT_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        requests.post(url, json=payload, timeout=20)
        print(f"✅ [TG] 消息发送成功")
    except Exception as e:
        print(f"❌ [TG] 发送失败: {e}")


# ================= 主逻辑 =================

def check_pixiv():
    now_beijing = datetime.utcnow() + timedelta(hours=8)
    time_threshold = now_beijing - timedelta(days=MAX_DAYS)

    print(f"⏰ 执行时间 (Beijing): {now_beijing}")
    print(f"🔍 搜索时间范围: 近 {MAX_DAYS * 24} 小时 (从 {time_threshold.strftime('%m-%d %H:%M')} 之后)")

    api = AppPixivAPI()
    try:
        api.auth(refresh_token=REFRESH_TOKEN)
    except Exception as e:
        print(f"❌ 登录失败: {e}")
        return

    sent_ids = load_history()
    all_new_novels = []
    seen_ids_this_run = set()

    if not KEYWORDS:
        print("❌ 未设置搜索关键词 (SEARCH_KEYWORDS)")
        return

    # 定义两种搜索模式：标签搜索 和 标题/简介搜索
    search_modes = [
        ("标签", "partial_match_for_tags"),
        ("标题/简介", "title_and_caption")
    ]

    for word in KEYWORDS:
        print(f"---- 搜索关键词: {word} ----")

        # 对每个关键词，分别执行两种模式的搜索
        for mode_name, target_mode in search_modes:
            # print(f"  > 正在搜索范围: {mode_name} ...") # 可选：打印详细日志

            try:
                # 使用当前循环的 target_mode，而不是全局配置的 SEARCH_TARGET
                json_result = api.search_novel(word=word, search_target=target_mode, sort="date_desc")
            except Exception as e:
                print(f"  ❌ 搜索API请求失败 ({mode_name}): {e}")
                continue

            if not json_result or 'novels' not in json_result:
                continue

            for novel in json_result.novels:
                n_id = str(novel.id)

                # --- 去重检查（关键步骤）---
                # 如果该ID已经在历史记录，或者在本次运行的另一种搜索模式中已添加，则跳过
                if n_id in sent_ids or n_id in seen_ids_this_run:
                    continue

                pub_dt_beijing = parse_to_beijing_time(novel.create_date)
                if not pub_dt_beijing: continue

                if pub_dt_beijing < time_threshold:
                    continue

                print(f"✨ 发现新作品 ({mode_name}匹配): {novel.title} ({pub_dt_beijing})")

                content_preview = "无法抓取内容"
                try:
                    text_res = api.novel_text(n_id)
                    if text_res and 'novel_text' in text_res:
                        content_preview = clean_html(text_res.novel_text)
                except Exception as e:
                    print(f"  抓取正文失败: {e}")

                # 构造链接
                url_pixez = f"pixez://novel/{n_id}"
                url_web = f"https://www.pixiv.net/novel/show.php?id={n_id}"

                # 获取作者信息
                author_id = str(novel.user.id)
                author_url = f"https://www.pixiv.net/users/{author_id}"

                all_new_novels.append({
                    "id": n_id,
                    "title": novel.title,
                    "author": novel.user.name,
                    "author_id": author_id,
                    "author_url": author_url,
                    "url_web": url_web,
                    "url_pixez": url_pixez,
                    "content_preview": content_preview,
                    "pub_date_obj": pub_dt_beijing,
                    "pub_date": pub_dt_beijing.strftime("%Y-%m-%d %H:%M"),
                    "tags": [t.name for t in novel.tags]
                })
                seen_ids_this_run.add(n_id)

            # 稍微暂停一下，避免请求过快触发限制
            time.sleep(0.5)

    if all_new_novels:
        # 按发布时间排序
        all_new_novels.sort(key=lambda x: x['pub_date_obj'])

        time_info = {
            "now_date": now_beijing.strftime("%m-%d"),
            "exec_time": now_beijing.strftime("%Y-%m-%d %H:%M:%S"),
            "range": f"{all_new_novels[0]['pub_date']} ~ {all_new_novels[-1]['pub_date']}"
        }

        # 倒序，让最新的显示在最前面（邮件/TG发送逻辑）
        all_new_novels.reverse()
        send_aggregated_tg(all_new_novels, time_info)
        send_aggregated_email(all_new_novels, time_info)

        new_history = sent_ids + list(seen_ids_this_run)
        save_history(new_history)
        print(f"✅ 已更新历史记录，新增 {len(seen_ids_this_run)} 条")
    else:
        print(f"📭 检查完成：过去 {MAX_DAYS * 24} 小时内无新内容")


if __name__ == "__main__":
    check_pixiv()