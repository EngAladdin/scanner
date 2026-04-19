# -*- coding: utf-8 -*-
"""واجهة ويب لفحص حسابات Gmail"""

from flask import Flask, render_template_string, request, jsonify, send_file
import threading
import json
from datetime import datetime
from main import GmailVerifierPro, scheduled_job

app = Flask(__name__)
verifier = GmailVerifierPro()

# قالب HTML
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>مدقق حسابات Gmail</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 20px; }
        .container { max-width: 1200px; margin: auto; }
        .header { text-align: center; color: white; margin-bottom: 30px; }
        .header h1 { font-size: 48px; margin-bottom: 10px; }
        .header p { font-size: 18px; opacity: 0.9; }
        .card { background: white; border-radius: 15px; padding: 25px; margin-bottom: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.2); }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 20px; }
        .stat-card { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; text-align: center; cursor: pointer; transition: transform 0.3s; }
        .stat-card:hover { transform: translateY(-5px); }
        .stat-card.live { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }
        .stat-card.disabled { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }
        .stat-card.invalid { background: linear-gradient(135deg, #fa709a 0%, #fee140 100%); }
        .stat-number { font-size: 36px; font-weight: bold; }
        .stat-label { font-size: 14px; margin-top: 10px; }
        button { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; padding: 12px 30px; border-radius: 25px; font-size: 16px; cursor: pointer; margin: 5px; transition: transform 0.3s; }
        button:hover { transform: scale(1.05); }
        button.danger { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }
        button.success { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }
        .progress-bar { width: 100%; height: 30px; background: #e0e0e0; border-radius: 15px; overflow: hidden; margin: 20px 0; }
        .progress-fill { height: 100%; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); transition: width 0.3s; display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; }
        .results-table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        .results-table th, .results-table td { padding: 12px; text-align: right; border-bottom: 1px solid #ddd; }
        .results-table th { background: #667eea; color: white; }
        .results-table tr:hover { background: #f5f5f5; }
        .live { color: #11998e; font-weight: bold; }
        .disabled { color: #f5576c; font-weight: bold; }
        .invalid { color: #fa709a; font-weight: bold; }
        .error { color: #ff6b6b; font-weight: bold; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .loader { border: 3px solid #f3f3f3; border-top: 3px solid #667eea; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 20px auto; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔥 مدقق حسابات Gmail</h1>
