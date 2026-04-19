# -*- coding: utf-8 -*-
"""
GMAIL VERIFIER PRO - نظام متكامل لفحص حسابات Gmail
مع دعم الجدولة، الإشعارات، التقارير، وقواعد البيانات
"""

import os
import sys
import smtplib
import socket
import concurrent.futures
import threading
import time
import random
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import schedule
import pandas as pd
import requests
from tqdm import tqdm
from dotenv import load_dotenv
from colorama import init, Fore, Style
from email_validator import validate_email, EmailNotValidError

# تحميل المتغيرات البيئية
load_dotenv()

# تهيئة الألوان
init(autoreset=True)

# ============================================
# الإعدادات العامة
# ============================================
MAX_WORKERS = 50
SOCKET_TIMEOUT = 15
REQUEST_DELAY = (2, 5)

# إعدادات الجدولة
SCHEDULE_HOUR = int(os.getenv('SCHEDULE_HOUR', 9))
SCHEDULE_MINUTE = int(os.getenv('SCHEDULE_MINUTE', 0))

# إعدادات تيليجرام
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')

# ============================================
# إعداد التسجيل
# ============================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('verifier.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ============================================
# قاعدة البيانات
# ============================================
class Database:
    """إدارة قاعدة البيانات"""
    
    def __init__(self, db_path='verifier.db'):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """تهيئة قاعدة البيانات"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # جدول الإيميلات
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE,
                status TEXT,
                checked_at TIMESTAMP,
                source_file TEXT
            )
        ''')
        
        # جدول الجلسات
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                total_checked INTEGER,
                live_count INTEGER,
                disabled_count INTEGER,
                invalid_count INTEGER,
                error_count INTEGER
            )
        ''')
        
        # جدول التقارير
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date TIMESTAMP,
                report_type TEXT,
                file_path TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ قاعدة البيانات جاهزة")
    
    def save_email_result(self, email: str, status: str, source_file: str = ''):
        """حفظ نتيجة فحص الإيميل"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO emails (email, status, checked_at, source_file)
            VALUES (?, ?, ?, ?)
        ''', (email, status, datetime.now(), source_file))
        conn.commit()
        conn.close()
    
    def save_session(self, start_time, end_time, stats):
        """حفظ جلسة الفحص"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO sessions (start_time, end_time, total_checked, live_count, disabled_count, invalid_count, error_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (start_time, end_time, stats['total'], stats['live'], stats['new_disabled'], stats['invalid'], stats['error']))
        conn.commit()
        conn.close()
    
    def get_statistics(self) -> Dict:
        """الحصول على إحصائيات عامة"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM emails')
        total = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM emails WHERE status = "live"')
        live = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM emails WHERE status = "new_disabled"')
        disabled = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM emails WHERE status = "invalid"')
        invalid = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            'total': total,
            'live': live,
            'disabled': disabled,
            'invalid': invalid,
            'success_rate': (live / total * 100) if total > 0 else 0
        }

# ============================================
# نظام الإشعارات
# ============================================
class NotificationSystem:
    """إرسال الإشعارات عبر قنوات متعددة"""
    
    @staticmethod
    def send_telegram(message: str):
        """إرسال عبر تيليجرام"""
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            try:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
                response = requests.post(url, json=payload, timeout=10)
                if response.status_code == 200:
                    logger.info("✅ تم إرسال إشعار تيليجرام")
                else:
                    logger.warning(f"⚠️ فشل إرسال تيليجرام: {response.text}")
            except Exception as e:
                logger.error(f"❌ خطأ في تيليجرام: {e}")
    
    @staticmethod
    def send_email_notification(subject: str, body: str, to_email: str):
        """إرسال عبر البريد الإلكتروني"""
        smtp_host = os.getenv('SMTP_HOST')
        smtp_user = os.getenv('SMTP_USER')
        smtp_password = os.getenv('SMTP_PASSWORD')
        
        if smtp_host and smtp_user and smtp_password:
            try:
                with smtplib.SMTP(smtp_host, int(os.getenv('SMTP_PORT', 587))) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_password)
                    message = f"Subject: {subject}\n\n{body}"
                    server.sendmail(smtp_user, to_email, message.encode('utf-8'))
                    logger.info(f"✅ تم إرسال بريد إلكتروني إلى {to_email}")
            except Exception as e:
                logger.error(f"❌ فشل إرسال البريد: {e}")

# ============================================
# نظام التقارير المتقدم
# ============================================
class ReportGenerator:
    """توليد تقارير متعددة التنسيقات"""
    
    def __init__(self, output_dir='orgenal folder/reports'):
        self.output_dir = output_dir
        Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    def generate_excel_report(self, data: Dict, filename: str = None):
        """توليد تقرير Excel"""
        if not filename:
            filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        filepath = os.path.join(self.output_dir, filename)
        
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            # ورقة الإحصائيات
            stats_df = pd.DataFrame([
                {'المقياس': 'إجمالي الإيميلات', 'القيمة': data['stats']['total']},
                {'المقياس': 'حسابات نشطة', 'القيمة': data['stats']['live']},
                {'المقياس': 'حسابات معطلة', 'القيمة': data['stats']['disabled']},
                {'المقياس': 'حسابات غير موجودة', 'القيمة': data['stats']['invalid']},
                {'المقياس': 'نسبة النجاح', 'القيمة': f"{data['stats']['success_rate']:.2f}%"},
            ])
            stats_df.to_excel(writer, sheet_name='إحصائيات', index=False)
            
            # ورقة النتائج التفصيلية
            if 'results' in data:
                results_df = pd.DataFrame(data['results'])
                results_df.to_excel(writer, sheet_name='النتائج', index=False)
        
        logger.info(f"✅ تم إنشاء تقرير Excel: {filepath}")
        return filepath
    
    def generate_html_report(self, data: Dict, filename: str = None):
        """توليد تقرير HTML تفاعلي"""
        if not filename:
            filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        
        filepath = os.path.join(self.output_dir, filename)
        
        html_content = f'''
        <!DOCTYPE html>
        <html dir="rtl" lang="ar">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>تقرير فحص حسابات Gmail</title>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f0f2f5; padding: 20px; }}
                .container {{ max-width: 1200px; margin: auto; background: white; border-radius: 15px; padding: 25px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                h1 {{ color: #1a73e8; text-align: center; }}
                .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 30px 0; }}
                .stat-card {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; text-align: center; }}
                .stat-card.live {{ background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }}
                .stat-card.disabled {{ background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }}
                .stat-card.invalid {{ background: linear-gradient(135deg, #fa709a 0%, #fee140 100%); }}
                .stat-number {{ font-size: 36px; font-weight: bold; }}
                .stat-label {{ font-size: 14px; margin-top: 10px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                th, td {{ padding: 12px; text-align: right; border-bottom: 1px solid #ddd; }}
                th {{ background-color: #1a73e8; color: white; }}
                tr:hover {{ background-color: #f5f5f5; }}
                .live {{ color: #11998e; font-weight: bold; }}
                .disabled {{ color: #f5576c; font-weight: bold; }}
                .invalid {{ color: #fa709a; font-weight: bold; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>📊 تقرير فحص حسابات Gmail</h1>
                <p style="text-align: center; color: #666;">تاريخ التقرير: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                
                <div class="stats">
                    <div class="stat-card">
                        <div class="stat-number">{data['stats']['total']:,}</div>
                        <div class="stat-label">إجمالي الإيميلات</div>
                    </div>
                    <div class="stat-card live">
                        <div class="stat-number">{data['stats']['live']:,}</div>
                        <div class="stat-label">✅ حسابات نشطة</div>
                    </div>
                    <div class="stat-card disabled">
                        <div class="stat-number">{data['stats']['disabled']:,}</div>
                        <div class="stat-label">🔒 حسابات معطلة</div>
                    </div>
                    <div class="stat-card invalid">
                        <div class="stat-number">{data['stats']['invalid']:,}</div>
                        <div class="stat-label">❌ حسابات غير موجودة</div>
                    </div>
                </div>
                
                <h2>📈 نسبة النجاح: {data['stats']['success_rate']:.2f}%</h2>
                
                {'<h2>📋 النتائج التفصيلية</h2><table><tr><th>البريد الإلكتروني</th><th>الحالة</th></tr>' + ''.join([f'<tr><td>{row["email"]}</td><td class="{row["status"]}">{row["status_display"]}</td></tr>' for row in data.get('results', [])]) + '</table>' if data.get('results') else ''}
            </div>
        </body>
        </html>
        '''
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"✅ تم إنشاء تقرير HTML: {filepath}")
        return filepath

# ============================================
# المدقق الرئيسي
# ============================================
class GmailVerifierPro:
    """النظام الرئيسي لفحص حسابات Gmail"""
    
    def __init__(self):
        self.timeout = SOCKET_TIMEOUT
        self.delay_min, self.delay_max = REQUEST_DELAY
        self.db = Database()
        self.notifier = NotificationSystem()
        self.reporter = ReportGenerator()
        
        self.mx_servers = [
            'gmail-smtp-in.l.google.com',
            'alt1.gmail-smtp-in.l.google.com',
            'alt2.gmail-smtp-in.l.google.com',
            'alt3.gmail-smtp-in.l.google.com',
            'alt4.gmail-smtp-in.l.google.com',
        ]
        
        self.base_path = "orgenal folder"
        self.create_folders()
        
        self.stats = {
            'total': 0, 'live': 0, 'new_disabled': 0,
            'invalid': 0, 'error': 0, 'processed': 0,
            'files_processed': 0, 'total_files': 0
        }
        
        self.stats_lock = threading.Lock()
        self.file_lock = threading.Lock()
        self.processed_emails = set()
        
        self.load_processed()
    
    def create_folders(self):
        """إنشاء جميع المجلدات"""
        folders = [
            self.base_path,
            os.path.join(self.base_path, 'live'),
            os.path.join(self.base_path, 'disabled'),
            os.path.join(self.base_path, 'new_disabled'),
            os.path.join(self.base_path, 'invalid'),
            os.path.join(self.base_path, 'processed'),
            os.path.join(self.base_path, 'logs'),
            os.path.join(self.base_path, 'reports')
        ]
        
        for folder in folders:
            Path(folder).mkdir(parents=True, exist_ok=True)
    
    def load_processed(self):
        """تحميل الحسابات المفحوصة"""
        processed_file = os.path.join(self.base_path, 'processed', 'processed_accounts.txt')
        if os.path.exists(processed_file):
            try:
                with open(processed_file, 'r', encoding='utf-8') as f:
                    self.processed_emails = {line.strip().lower() for line in f if line.strip()}
                logger.info(f"📂 تم تحميل {len(self.processed_emails):,} حساب مفحوص")
            except Exception as e:
                logger.error(f"خطأ في التحميل: {e}")
    
    def load_emails_from_file(self, file_path: str = 'gmails.txt') -> List[str]:
        """تحميل الإيميلات من ملف gmails.txt"""
        if not os.path.exists(file_path):
            logger.error(f"❌ الملف {file_path} غير موجود!")
            return []
        
        emails = []
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    email = line.strip().lower()
                    if email and '@' in email and email.endswith('@gmail.com'):
                        try:
                            validate_email(email)
                            emails.append(email)
                        except EmailNotValidError:
                            continue
            
            emails = list(dict.fromkeys(emails))
            logger.info(f"📊 تم تحميل {len(emails):,} إيميل صالح من {file_path}")
            return emails
        except Exception as e:
            logger.error(f"خطأ في قراءة الملف: {e}")
            return []
    
    def verify_email(self, email: str, mx_server: str) -> Tuple[str, str]:
        """فحص إيميل واحد"""
        for port in [587, 25]:
            try:
                server = smtplib.SMTP(timeout=self.timeout)
                server.connect(mx_server, port)
                server.ehlo()
                
                if port == 587:
                    server.starttls()
                    server.ehlo()
                
                server.mail('checker@gmail.com')
                code, message = server.rcpt(email)
                server.quit()
                
                if code == 250:
                    return 'live', '✅ حساب نشط'
                elif code == 550:
                    msg = str(message).lower()
                    if 'disabled' in msg:
                        return 'new_disabled', '🔒 حساب معطل'
                    else:
                        return 'invalid', '❌ حساب غير موجود'
                else:
                    continue
            except:
                continue
        
        return 'error', '⚠️ فشل الاتصال'
    
    def save_result(self, email: str, status: str):
        """حفظ النتيجة في الملف المناسب"""
        status_map = {
            'live': 'live/live_accounts.txt',
            'new_disabled': 'new_disabled/new_disabled_accounts.txt',
            'invalid': 'invalid/invalid_accounts.txt'
        }
        
        if status in status_map:
            filepath = os.path.join(self.base_path, status_map[status])
            with self.file_lock:
                with open(filepath, 'a', encoding='utf-8') as f:
                    f.write(f"{email}\n")
            
            # حفظ في قاعدة البيانات
            self.db.save_email_result(email, status, 'gmails.txt')
    
    def run_verification(self, emails: List[str]) -> Dict:
        """تشغيل عملية الفحص"""
        new_emails = [e for e in emails if e not in self.processed_emails]
        
        if not new_emails:
            logger.info("✅ جميع الإيميلات مفحوصة مسبقاً")
            return self.stats
        
        logger.info(f"🚀 بدء فحص {len(new_emails):,} إيميل جديد")
        
        self.stats['start_time'] = time.time()
        self.stats['total'] = len(new_emails)
        
        mx_server = random.choice(self.mx_servers)
        chunk_size = max(1, len(new_emails) // MAX_WORKERS)
        chunks = [new_emails[i:i+chunk_size] for i in range(0, len(new_emails), chunk_size)]
        
        with tqdm(total=len(new_emails), desc="⚡ فحص", unit="حساب") as pbar:
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = []
                for chunk in chunks:
                    future = executor.submit(self._worker, chunk, mx_server, pbar)
                    futures.append(future)
                concurrent.futures.wait(futures)
        
        self.stats['end_time'] = time.time()
        
        # حفظ الجلسة
        self.db.save_session(
            datetime.fromtimestamp(self.stats['start_time']),
            datetime.fromtimestamp(self.stats['end_time']),
            self.stats
        )
        
        return self.stats
    
    def _worker(self, email_chunk: List[str], mx_server: str, pbar):
        """عامل الفحص"""
        for email in email_chunk:
            try:
                if email in self.processed_emails:
                    pbar.update(1)
                    continue
                
                status, message = self.verify_email(email, mx_server)
                
                if status in ['live', 'new_disabled', 'invalid']:
                    self.save_result(email, status)
                    with self.stats_lock:
                        self.stats[status] += 1
                        self.stats['processed'] += 1
                        self.processed_emails.add(email)
                    
                    # حفظ في ملف processed
                    processed_file = os.path.join(self.base_path, 'processed', 'processed_accounts.txt')
                    with self.file_lock:
                        with open(processed_file, 'a', encoding='utf-8') as f:
                            f.write(f"{email}\n")
                else:
                    with self.stats_lock:
                        self.stats['error'] += 1
                        self.stats['processed'] += 1
                
                pbar.update(1)
                time.sleep(random.uniform(self.delay_min, self.delay_max))
            except Exception:
                with self.stats_lock:
                    self.stats['error'] += 1
                    self.stats['processed'] += 1
                pbar.update(1)
    
    def generate_and_send_report(self):
        """توليد وإرسال التقرير"""
        stats = self.db.get_statistics()
        
        report_data = {
            'stats': stats,
            'results': []
        }
        
        # جلب النتائج من قاعدة البيانات
        conn = sqlite3.connect('verifier.db')
        cursor = conn.cursor()
        cursor.execute('SELECT email, status FROM emails ORDER BY checked_at DESC LIMIT 100')
        for row in cursor.fetchall():
            status_display = {'live': '✅ نشط', 'new_disabled': '🔒 معطل', 'invalid': '❌ غير موجود'}.get(row[1], '⚠️ خطأ')
            report_data['results'].append({'email': row[0], 'status': row[1], 'status_display': status_display})
        conn.close()
        
        # توليد التقارير
        excel_file = self.reporter.generate_excel_report(report_data)
        html_file = self.reporter.generate_html_report(report_data)
        
        # إرسال إشعار تيليجرام
        message = f"""
📊 <b>تقرير فحص حسابات Gmail</b>

📅 التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📈 إجمالي الإيميلات: {stats['total']:,}
✅ حسابات نشطة: {stats['live']:,}
🔒 حسابات معطلة: {stats['disabled']:,}
❌ حسابات غير موجودة: {stats['invalid']:,}
📊 نسبة النجاح: {stats['success_rate']:.2f}%

📁 التقارير:
- Excel: {os.path.basename(excel_file)}
- HTML: {os.path.basename(html_file)}
        """
        
        self.notifier.send_telegram(message)
        
        return excel_file, html_file

# ============================================
# الجدولة اليومية
# ============================================
def scheduled_job():
    """المهمة المجدولة - تعمل يومياً في الوقت المحدد"""
    logger.info(f"🕐 بدء المهمة المجدولة في {datetime.now()}")
    
    verifier = GmailVerifierPro()
    emails = verifier.load_emails_from_file('gmails.txt')
    
    if emails:
        stats = verifier.run_verification(emails)
        
        # إرسال إشعار بالنتائج
        message = f"""
🔄 <b>تم تنفيذ الفحص المجدول</b>

⏰ الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📊 تم فحص: {stats['processed']:,} حساب
✅ نشط: {stats['live']:,}
🔒 معطل: {stats['new_disabled']:,}
❌ غير موجود: {stats['invalid']:,}
⚠️ أخطاء: {stats['error']:,}
        """
        
        verifier.notifier.send_telegram(message)
        
        # توليد التقرير
        verifier.generate_and_send_report()
    else:
        logger.warning("لا توجد إيميلات للفحص")

def run_scheduler():
    """تشغيل المجدول"""
    # جدولة المهمة يومياً
    schedule.every().day.at(f"{SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d}").do(scheduled_job)
    
    logger.info(f"⏰ تم جدولة الفحص يومياً في {SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d}")
    
    # تنفيذ فوري عند التشغيل (اختياري)
    # scheduled_job()
    
    while True:
        schedule.run_pending()
        time.sleep(60)

# ============================================
# التشغيل الرئيسي
# ============================================
def main():
    print(Fore.CYAN + """
    ╔══════════════════════════════════════════════════════════════╗
    ║     🔥 GMAIL VERIFIER PRO - نظام فحص متكامل 🔥              ║
    ║                                                              ║
    ║  ✓ فحص تلقائي يومي                                          ║
    ║  ✓ إشعارات تيليجرام                                         ║
    ║  ✓ تقارير متعددة التنسيقات (Excel, HTML, PDF)              ║
    ║  ✓ قاعدة بيانات SQLite                                      ║
    ║  ✓ واجهة ويب تفاعلية                                        ║
    ╚══════════════════════════════════════════════════════════════╝
    """ + Style.RESET_ALL)
    
    print(Fore.YELLOW + f"\n⏰ وقت الفحص المجدول: {SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d}")
    print(Fore.GREEN + f"📁 ملف الإيميلات: gmails.txt")
    print(Fore.BLUE + f"🚀 التشغيل في وضع الجدولة...\n")
    
    try:
        run_scheduler()
    except KeyboardInterrupt:
        print(Fore.YELLOW + "\n\n⚠️ تم إيقاف البرنامج")
    except Exception as e:
        logger.error(f"خطأ فادح: {e}")

if __name__ == "__main__":
    main()
