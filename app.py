#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Propertly.io SMS Automation System - Enhanced Version
Automatyczna wysyłka SMS do nowych ofert nieruchomości z rozszerzonymi filtrami
"""

import os
import json
import base64
import time
import threading
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import requests
import schedule

# === CONFIGURATION ===
PORT = int(os.environ.get('PORT', 8080))
PASSWORD = "H4ctar3s"

# Propertly.io credentials
PROPERTLY_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3NzI3OTUxMDUsInN1YiI6IjVmMGNmNDEzLTZhYTItNGEzOC1hYzEzLTc5Y2FiZWYwODhmYiIsImlhdCI6MTc3MDE3MDM5Mywic2NvcGUiOltdfQ.nLY1TbV2T6u3xnBiWQGDy-6Oaxm4KuF2YBDWJxpxt-I"
PROPERTLY_REFRESH_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3Nzc5NzkxMDUsInN1YiI6IjVmMGNmNDEzLTZhYTItNGEzOC1hYzEzLTc5Y2FiZWYwODhmYiIsImlhdCI6MTc3MDE3MDM5Mywic2NvcGUiOltdfQ.S9cXDoLbdGAxEWreZL-r5grC4TeZeOEzacuAlLyMCK8"

# SMS API
TOKEN_URL = "https://uslugidlafirm.play.pl/oauth/token-jwt"
SEND_URL = "https://uslugidlafirm.play.pl/api/bramkasms/sendSms"

# Sender accounts
SENDER_ACCOUNTS = {
    "kasia": {
        "name": "Kasia",
        "clientId": "sU2FzpO3Q7fpnas8",
        "clientSecret": "z42QdDTO2hQB0IkGRlrnFzFa4ze8dk2rm6b3egU4rw2RM9T5ocH22EmxmkjYyPGb",
        "senderMsisdn": "48530805774"
    },
    "gosia": {
        "name": "Gosia",
        "clientId": "JHeAcveUAYPJ1ih1",
        "clientSecret": "N5CGRrQexnKp20I50UJpU9FG3n4nb7jt9nEsldyxnxEFABGnV79OEUKSXnHunOKH",
        "senderMsisdn": "48881475475"
    },
    "daria": {
        "name": "Daria",
        "clientId": "ob3jrO9YXQ76n8oN",
        "clientSecret": "hnM9ee7akkuR4ievdJ3uSRrEAtAnYeXUhcXFHY3l3DE6WQQI5CwUxcEiHBGmDFdg",
        "senderMsisdn": "48533344257"
    }
}

# Voivodeships
VOIVODESHIPS = {
    "dolnoslaskie": "dolnośląskie",
    "kujawsko_pomorskie": "kujawsko-pomorskie",
    "lubelskie": "lubelskie",
    "lubuskie": "lubuskie",
    "lodzkie": "łódzkie",
    "malopolskie": "małopolskie",
    "mazowieckie": "mazowieckie",
    "opolskie": "opolskie",
    "podkarpackie": "podkarpackie",
    "podlaskie": "podlaskie",
    "pomorskie": "pomorskie",
    "slaskie": "śląskie",
    "swietokrzyskie": "świętokrzyskie",
    "warminsko_mazurskie": "warmińsko-mazurskie",
    "wielkopolskie": "wielkopolskie",
    "zachodniopomorskie": "zachodniopomorskie"
}

# Global state
campaigns = {}
sent_messages = {}
pending_queue = []

# Working hours: Mon-Sat, 9:00-18:00
def is_working_hours():
    """Check if current time is within working hours"""
    now = datetime.now()
    if now.weekday() == 6:  # Sunday
        return False
    hour = now.hour
    return 9 <= hour < 18

def normalize_phone(phone):
    """Normalize phone number to format 48XXXXXXXXX"""
    digits = ''.join(filter(str.isdigit, str(phone)))
    if not digits:
        return None
    
    if digits.startswith('00'):
        digits = digits[2:]
    if digits.startswith('0') and len(digits) > 9:
        digits = digits[1:]
    if len(digits) == 9:
        digits = '48' + digits
    
    if len(digits) == 11 and digits.startswith('48'):
        return digits
    return None

def extract_phone_from_offer(offer):
    """Extract phone number from Propertly offer"""
    contacts = offer.get('contacts', [])
    for contact in contacts:
        if contact.get('contact_type') == 'phone':
            phone = contact.get('contact')
            normalized = normalize_phone(phone)
            if normalized:
                return normalized
    return None

def fetch_offers_from_propertly(campaign_config):
    """Fetch offers from Propertly.io based on campaign filters"""
    url = "https://app.propertly.io/api/offers"
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "cookie": f"token={PROPERTLY_TOKEN}; refresh_token={PROPERTLY_REFRESH_TOKEN}",
    }
    
    filters = []
    
    # Location filter
    location_filter = campaign_config.get('location_filter', {})
    if location_filter:
        filters.append({
            "field": "address",
            "condition": "ANY_GROUP_EQUAL",
            "value": [location_filter]
        })
    
    # Time range filter
    last_n_days = campaign_config.get('last_n_days', 1)
    filters.append({
        "field": "date_smart_last_seen",
        "value": last_n_days,
        "condition": "LAST_N_DAYS"
    })
    
    # Issuer type filter
    issuer_type = campaign_config.get('issuer_type', 'REAL_ESTATE_AGENCY')
    filters.append({
        "field": "issuer_type",
        "value": [issuer_type],
        "condition": "IN"
    })
    
    # Market type filter (PRIMARY/SECONDARY)
    market_type = campaign_config.get('market_type')
    if market_type:
        filters.append({
            "field": "market_type",
            "value": market_type,
            "condition": "EQUAL"
        })
    
    # Price filters
    min_price = campaign_config.get('min_price')
    if min_price:
        filters.append({
            "field": "price",
            "value": int(min_price),
            "condition": "GREATER_OR_EQUAL_THAN"
        })
    
    max_price = campaign_config.get('max_price')
    if max_price:
        filters.append({
            "field": "price",
            "value": int(max_price),
            "condition": "LESSER_OR_EQUAL_THAN"
        })
    
    # Price per meter filters
    min_price_per_meter = campaign_config.get('min_price_per_meter')
    if min_price_per_meter:
        filters.append({
            "field": "price_per_meter",
            "value": int(min_price_per_meter),
            "condition": "GREATER_OR_EQUAL_THAN"
        })
    
    max_price_per_meter = campaign_config.get('max_price_per_meter')
    if max_price_per_meter:
        filters.append({
            "field": "price_per_meter",
            "value": int(max_price_per_meter),
            "condition": "LESSER_OR_EQUAL_THAN"
        })
    
    # Area filters
    min_area = campaign_config.get('min_area')
    if min_area:
        filters.append({
            "field": "area",
            "value": float(min_area),
            "condition": "GREATER_OR_EQUAL_THAN"
        })
    
    max_area = campaign_config.get('max_area')
    if max_area:
        filters.append({
            "field": "area",
            "value": float(max_area),
            "condition": "LESSER_OR_EQUAL_THAN"
        })
    
    # Rooms filters
    min_rooms = campaign_config.get('min_rooms')
    if min_rooms:
        filters.append({
            "field": "rooms_number",
            "value": int(min_rooms),
            "condition": "GREATER_OR_EQUAL_THAN"
        })
    
    max_rooms = campaign_config.get('max_rooms')
    if max_rooms:
        filters.append({
            "field": "rooms_number",
            "value": int(max_rooms),
            "condition": "LESSER_OR_EQUAL_THAN"
        })
    
    # Active offers only
    if campaign_config.get('only_active', True):
        filters.append({
            "field": "is_active",
            "value": True,
            "condition": "EQUAL"
        })
    
    # Unique offers only
    if campaign_config.get('only_unique', True):
        filters.append({
            "field": "is_unique",
            "value": True,
            "condition": "EQUAL"
        })
    
    # Location proximity
    filters.append({
        "field": "location",
        "value": 0,
        "condition": "PROXIMITY"
    })
    
    # Offer types
    offer_types = campaign_config.get('offer_types', [
        "APARTMENT_SALES", "COMMERCIAL_BUILDING_SALES", "HOUSE_SALES",
        "INDUSTRIAL_BUILDING_SALES", "LAND_SALES", "OFFICE_SALES", "WAREHOUSE_SALES"
    ])
    
    body = {
        "page": 1,
        "size": 50,
        "offer_type": json.dumps(offer_types),
        "filters": json.dumps(filters),
        "sorts": '[{"field":"date_smart_last_seen","ascending":false}]'
    }
    
    try:
        response = requests.post(url, headers=headers, json=body, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get('results', [])
    except Exception as e:
        print(f"Error fetching offers: {e}")
        return []

def send_sms_to_number(phone, text, sender_account):
    """Send SMS to a single number"""
    try:
        auth = base64.b64encode(f"{sender_account['clientId']}:{sender_account['clientSecret']}".encode()).decode('ascii')
        token_response = requests.post(
            TOKEN_URL,
            headers={
                'Authorization': f'Basic {auth}',
                'Accept': 'application/json'
            },
            timeout=20
        )
        
        if token_response.status_code != 200:
            return False, f"Token error: {token_response.status_code}"
        
        token = token_response.json().get('access_token')
        
        send_response = requests.post(
            SEND_URL,
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            json={
                'from': sender_account['senderMsisdn'],
                'text': text,
                'to': [phone]
            },
            timeout=20
        )
        
        if send_response.status_code in (200, 201, 202):
            return True, "Success"
        else:
            return False, f"Send error: {send_response.status_code}"
            
    except Exception as e:
        return False, str(e)

def process_campaign_offers(campaign_id):
    """Process offers for a campaign and send SMS"""
    campaign = campaigns.get(campaign_id)
    if not campaign or not campaign.get('active'):
        return
    
    print(f"Processing campaign: {campaign['name']}")
    
    offers = fetch_offers_from_propertly(campaign.get('filters', {}))
    print(f"Found {len(offers)} offers")
    
    sender_key = campaign.get('sender', 'kasia')
    sender_account = SENDER_ACCOUNTS.get(sender_key, SENDER_ACCOUNTS['kasia'])
    
    sms_text = campaign.get('sms_text', '')
    
    for offer in offers:
        offer_id = offer.get('id')
        
        if offer_id in sent_messages:
            continue
        
        phone = extract_phone_from_offer(offer)
        if not phone:
            continue
        
        already_sent = False
        for msg_id, msg_data in sent_messages.items():
            if msg_data.get('phone') == phone:
                sent_at = msg_data.get('sent_at', 0)
                if time.time() - sent_at < 90 * 24 * 3600:
                    already_sent = True
                    break
        
        if already_sent:
            print(f"Phone {phone} already contacted in last 90 days")
            continue
        
        if not is_working_hours():
            pending_queue.append({
                'offer_id': offer_id,
                'phone': phone,
                'sms_text': sms_text,
                'sender_account': sender_account,
                'campaign_id': campaign_id
            })
            print(f"Added to queue (outside working hours): {phone}")
            continue
        
        success, message = send_sms_to_number(phone, sms_text, sender_account)
        
        if success:
            sent_messages[offer_id] = {
                'phone': phone,
                'sent_at': time.time(),
                'campaign_id': campaign_id,
                'sender': sender_account['name'],
                'text': sms_text,
                'offer': offer
            }
            print(f"✅ SMS sent to {phone} from {sender_account['name']}")
            save_state()
        else:
            print(f"❌ Failed to send SMS to {phone}: {message}")
        
        time.sleep(0.5)

def process_pending_queue():
    """Process pending SMS from queue during working hours"""
    if not is_working_hours():
        return
    
    global pending_queue
    to_process = pending_queue[:]
    pending_queue = []
    
    for item in to_process:
        offer_id = item['offer_id']
        
        if offer_id in sent_messages:
            continue
        
        phone = item['phone']
        sms_text = item['sms_text']
        sender_account = item['sender_account']
        campaign_id = item['campaign_id']
        
        success, message = send_sms_to_number(phone, sms_text, sender_account)
        
        if success:
            sent_messages[offer_id] = {
                'phone': phone,
                'sent_at': time.time(),
                'campaign_id': campaign_id,
                'sender': sender_account['name'],
                'text': sms_text
            }
            print(f"✅ SMS sent from queue to {phone}")
            save_state()
        else:
            print(f"❌ Failed to send SMS from queue to {phone}: {message}")
            pending_queue.append(item)
        
        time.sleep(0.5)

def save_state():
    """Save campaigns and sent messages to file"""
    state = {
        'campaigns': campaigns,
        'sent_messages': sent_messages,
        'pending_queue': pending_queue
    }
    with open('propertly_sms_state.json', 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def load_state():
    """Load campaigns and sent messages from file"""
    global campaigns, sent_messages, pending_queue
    try:
        with open('propertly_sms_state.json', 'r', encoding='utf-8') as f:
            state = json.load(f)
            campaigns = state.get('campaigns', {})
            sent_messages = state.get('sent_messages', {})
            pending_queue = state.get('pending_queue', [])
    except FileNotFoundError:
        pass

def scheduler_thread():
    """Background thread for scheduled tasks"""
    schedule.every(15).minutes.do(run_all_campaigns)
    schedule.every(5).minutes.do(process_pending_queue)
    
    while True:
        schedule.run_pending()
        time.sleep(60)

def run_all_campaigns():
    """Run all active campaigns"""
    for campaign_id in list(campaigns.keys()):
        try:
            process_campaign_offers(campaign_id)
        except Exception as e:
            print(f"Error processing campaign {campaign_id}: {e}")

# HTML Template - Enhanced with more filters and COMPACT SPACING
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SMS Automation System - Enhanced</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #ffffff;
            color: #2c3e50;
            line-height: 1.6;
        }

        /* Header */
        .header {
            background: #2c3e50;
            color: white;
            padding: 20px 0;
            position: sticky;
            top: 0;
            z-index: 100;
            border-bottom: 1px solid #1a252f;
        }

        .header-content {
            max-width: 1400px;
            margin: 0 auto;
            padding: 0 30px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .header h1 {
            font-size: 18px;
            font-weight: 600;
            letter-spacing: 0.5px;
        }

        .header-right {
            display: flex;
            align-items: center;
            gap: 20px;
        }

        .status-badge {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            padding: 6px 14px;
            background: rgba(255,255,255,0.1);
            border-radius: 4px;
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #27ae60;
        }

        .status-dot.inactive {
            background: #95a5a6;
        }

        .logout-btn {
            padding: 8px 16px;
            background: transparent;
            color: white;
            border: 1px solid rgba(255,255,255,0.3);
            border-radius: 4px;
            cursor: pointer;
            font-size: 13px;
            transition: all 0.2s;
        }

        .logout-btn:hover {
            background: rgba(255,255,255,0.1);
        }

        /* Main Container */
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 30px;
        }

        /* Statistics Bar */
        .stats-section {
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 4px;
            padding: 30px;
            margin-bottom: 30px;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 30px;
        }

        .stat-item {
            text-align: center;
        }

        .stat-value {
            font-size: 40px;
            font-weight: 300;
            color: #2c3e50;
            margin-bottom: 8px;
        }

        .stat-label {
            font-size: 12px;
            color: #7f8c8d;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        /* Section */
        .section {
            margin-bottom: 50px;
        }

        .section-header {
            border-bottom: 2px solid #2c3e50;
            padding-bottom: 15px;
            margin-bottom: 25px;
        }

        .section-title {
            font-size: 20px;
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 5px;
        }

        .section-subtitle {
            font-size: 13px;
            color: #7f8c8d;
        }

        /* Info Cards */
        .info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 25px;
        }

        .info-card {
            display: flex;
            gap: 15px;
            padding: 20px;
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 3px;
        }

        .info-number {
            flex-shrink: 0;
            width: 40px;
            height: 40px;
            background: #2c3e50;
            color: white;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            font-size: 18px;
        }

        .info-content h3 {
            font-size: 14px;
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 6px;
        }

        .info-content p {
            font-size: 13px;
            color: #7f8c8d;
            line-height: 1.5;
        }

        .info-alert {
            padding: 15px 20px;
            background: #fff3cd;
            border: 1px solid #ffc107;
            border-left: 4px solid #ffc107;
            border-radius: 3px;
            font-size: 13px;
            color: #856404;
            line-height: 1.6;
        }

        .info-alert strong {
            font-weight: 600;
        }

        /* Form - COMPACT SPACING */
        .form-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
            margin-bottom: 10px;
        }

        .form-group {
            margin-bottom: 8px;
        }

        .form-group.full-width {
            grid-column: 1 / -1;
        }

        .form-label {
            display: block;
            margin-bottom: 5px;
            font-size: 13px;
            font-weight: 500;
            color: #2c3e50;
        }

        .form-input,
        .form-textarea,
        .form-select {
            width: 100%;
            padding: 8px 10px;
            border: 1px solid #dfe6e9;
            border-radius: 3px;
            font-size: 14px;
            font-family: inherit;
            transition: border-color 0.2s;
        }

        .form-input:focus,
        .form-textarea:focus,
        .form-select:focus {
            outline: none;
            border-color: #2c3e50;
        }

        .form-textarea {
            min-height: 70px;
            resize: vertical;
        }

        .form-hint {
            font-size: 11px;
            color: #95a5a6;
            margin-top: 3px;
        }

        /* Filter Section - COMPACT SPACING */
        .filter-section {
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 3px;
            padding: 12px 15px;
            margin-bottom: 10px;
        }

        .filter-section-title {
            font-size: 13px;
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 10px;
            padding-bottom: 8px;
            border-bottom: 1px solid #e9ecef;
        }

        .range-group {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }

        /* Checkboxes */
        .checkbox-group {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 6px;
        }

        .checkbox-group input[type="checkbox"] {
            width: 16px;
            height: 16px;
            cursor: pointer;
        }

        .checkbox-group label {
            cursor: pointer;
            font-size: 13px;
        }

        /* Sender Selection */
        .sender-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
            margin-bottom: 15px;
        }

        .sender-option {
            padding: 12px;
            border: 2px solid #e9ecef;
            border-radius: 3px;
            cursor: pointer;
            text-align: center;
            transition: all 0.2s;
            background: white;
        }

        .sender-option:hover {
            border-color: #bdc3c7;
        }

        .sender-option.selected {
            border-color: #2c3e50;
            background: #f8f9fa;
        }

        .sender-name {
            font-weight: 600;
            font-size: 14px;
            margin-bottom: 4px;
        }

        .sender-phone {
            font-size: 11px;
            color: #7f8c8d;
            font-family: monospace;
        }

        /* Buttons */
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 3px;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
        }

        .btn-primary {
            background: #2c3e50;
            color: white;
        }

        .btn-primary:hover {
            background: #34495e;
        }

        .btn-secondary {
            background: #95a5a6;
            color: white;
        }

        .btn-secondary:hover {
            background: #7f8c8d;
        }

        .btn-success {
            background: #27ae60;
            color: white;
        }

        .btn-success:hover {
            background: #229954;
        }

        .btn-danger {
            background: #e74c3c;
            color: white;
        }

        .btn-danger:hover {
            background: #c0392b;
        }

        .btn-small {
            padding: 6px 12px;
            font-size: 12px;
        }

        /* Campaign List */
        .campaign-grid {
            display: grid;
            gap: 15px;
        }

        .campaign-card {
            border: 1px solid #e9ecef;
            border-radius: 3px;
            padding: 20px;
            background: white;
        }

        .campaign-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 15px;
            padding-bottom: 15px;
            border-bottom: 1px solid #f8f9fa;
        }

        .campaign-name {
            font-size: 16px;
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 5px;
        }

        .campaign-status {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 2px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .campaign-status.active {
            background: #d4edda;
            color: #155724;
        }

        .campaign-status.inactive {
            background: #f8d7da;
            color: #721c24;
        }

        .campaign-info {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin-bottom: 15px;
            padding: 12px;
            background: #f8f9fa;
            border-radius: 3px;
        }

        .campaign-info-item {
            font-size: 12px;
        }

        .campaign-info-label {
            color: #7f8c8d;
            margin-bottom: 2px;
        }

        .campaign-info-value {
            color: #2c3e50;
            font-weight: 500;
        }

        .campaign-filters {
            font-size: 12px;
            color: #7f8c8d;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 3px;
            margin-bottom: 15px;
        }

        .campaign-text {
            font-size: 13px;
            color: #2c3e50;
            padding: 12px;
            background: #f8f9fa;
            border-left: 3px solid #2c3e50;
            margin-bottom: 15px;
        }

        .campaign-actions {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }

        /* Messages List */
        .message-list {
            display: grid;
            gap: 12px;
            max-height: 800px;
            overflow-y: auto;
        }

        .message-card {
            border: 1px solid #e9ecef;
            border-radius: 3px;
            padding: 15px;
            background: white;
        }

        .message-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
        }

        .message-phone {
            font-family: monospace;
            font-weight: 600;
            font-size: 13px;
        }

        .message-time {
            font-size: 11px;
            color: #95a5a6;
        }

        .message-meta {
            font-size: 12px;
            color: #7f8c8d;
            margin-bottom: 8px;
        }

        .message-text {
            font-size: 12px;
            color: #2c3e50;
            padding: 10px;
            background: #f8f9fa;
            border-left: 2px solid #2c3e50;
        }

        /* Alert */
        .alert {
            padding: 12px 15px;
            border-radius: 3px;
            margin-bottom: 15px;
            font-size: 13px;
            border-left: 3px solid;
        }

        .alert-success {
            background: #d4edda;
            color: #155724;
            border-color: #28a745;
        }

        .alert-error {
            background: #f8d7da;
            color: #721c24;
            border-color: #dc3545;
        }

        .alert-info {
            background: #d1ecf1;
            color: #0c5460;
            border-color: #17a2b8;
        }

        /* Empty State */
        .empty-state {
            text-align: center;
            padding: 50px 20px;
            color: #95a5a6;
            border: 1px dashed #dfe6e9;
            border-radius: 3px;
            background: #fafafa;
        }

        .empty-state-text {
            font-size: 14px;
        }

        /* Login */
        .login-screen {
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            background: #f5f5f5;
        }

        .login-box {
            background: white;
            padding: 40px;
            border-radius: 3px;
            border: 1px solid #e9ecef;
            width: 100%;
            max-width: 400px;
        }

        .login-title {
            text-align: center;
            margin-bottom: 30px;
            font-size: 20px;
            font-weight: 600;
            color: #2c3e50;
        }

        /* Utilities */
        .hidden {
            display: none !important;
        }

        /* Responsive */
        @media (max-width: 768px) {
            .container {
                padding: 20px;
            }

            .form-grid,
            .sender-grid,
            .campaign-info {
                grid-template-columns: 1fr;
            }

            .stats-grid {
                grid-template-columns: repeat(2, 1fr);
            }

            .info-grid {
                grid-template-columns: 1fr;
            }

            .range-group {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <!-- Login Screen -->
    <div id="loginScreen" class="login-screen">
        <div class="login-box">
            <h2 class="login-title">SMS Automation System</h2>
            <div class="form-group">
                <label class="form-label" for="password">Hasło dostępu</label>
                <input type="password" id="password" class="form-input" placeholder="Wprowadź hasło">
            </div>
            <button class="btn btn-primary" style="width: 100%;" onclick="login()">Zaloguj się</button>
            <div id="loginError" class="alert alert-error hidden" style="margin-top: 15px; margin-bottom: 0;">
                Nieprawidłowe hasło
            </div>
        </div>
    </div>

    <!-- Main App -->
    <div id="mainApp" class="hidden">
        <!-- Header -->
        <div class="header">
            <div class="header-content">
                <h1>SMS AUTOMATION SYSTEM - ENHANCED</h1>
                <div class="header-right">
                    <div class="status-badge">
                        <div class="status-dot" id="statusDot"></div>
                        <span id="statusText">System aktywny</span>
                    </div>
                    <button class="logout-btn" onclick="logout()">Wyloguj</button>
                </div>
            </div>
        </div>

        <!-- Main Content -->
        <div class="container">
            <!-- Statistics -->
            <div class="stats-section">
                <div class="stats-grid">
                    <div class="stat-item">
                        <div class="stat-value" id="totalCampaigns">0</div>
                        <div class="stat-label">Aktywne kampanie</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value" id="totalSent">0</div>
                        <div class="stat-label">Wysłane SMS</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value" id="queueSize">0</div>
                        <div class="stat-label">W kolejce</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value" id="workingHoursStatus">---</div>
                        <div class="stat-label">Status godzin pracy</div>
                    </div>
                </div>
            </div>

            <!-- How It Works -->
            <div class="section">
                <div class="section-header">
                    <h2 class="section-title">Jak działa system?</h2>
                    <p class="section-subtitle">Automatyczna wysyłka SMS do nowych ofert nieruchomości z Propertly.io</p>
                </div>

                <div class="info-grid">
                    <div class="info-card">
                        <div class="info-number">1</div>
                        <div class="info-content">
                            <h3>Tworzenie kampanii</h3>
                            <p>Wybierasz województwo, typ ogłoszeniodawcy, filtry cenowe, powierzchni, liczby pokoi oraz rodzaj rynku. System daje pełną kontrolę nad targetowaniem.</p>
                        </div>
                    </div>

                    <div class="info-card">
                        <div class="info-number">2</div>
                        <div class="info-content">
                            <h3>Automatyczne sprawdzanie</h3>
                            <p>System sprawdza nowe oferty w Propertly.io co 15 minut według Twoich precyzyjnych filtrów.</p>
                        </div>
                    </div>

                    <div class="info-card">
                        <div class="info-number">3</div>
                        <div class="info-content">
                            <h3>Zaawansowane filtrowanie</h3>
                            <p>Filtry obejmują cenę, cenę za m², powierzchnię, liczbę pokoi, rodzaj rynku (pierwotny/wtórny) oraz szczegółową lokalizację.</p>
                        </div>
                    </div>

                    <div class="info-card">
                        <div class="info-number">4</div>
                        <div class="info-content">
                            <h3>Inteligentna deduplikacja</h3>
                            <p>System pomija duplikaty i sprawdza, czy dany numer nie został kontaktowany w ciągu ostatnich 90 dni.</p>
                        </div>
                    </div>

                    <div class="info-card">
                        <div class="info-number">5</div>
                        <div class="info-content">
                            <h3>Wysyłka w godzinach pracy</h3>
                            <p>SMS wysyłane tylko pn-sb 9:00-18:00. Wiadomości poza tymi godzinami czekają w kolejce.</p>
                        </div>
                    </div>
                </div>

                <div class="info-alert">
                    <strong>Ważne:</strong> Używaj tylko znaków ASCII (bez polskich liter) w treści SMS. 
                    Maksymalna długość wiadomości to 160 znaków. 
                    Każdy numer telefonu jest kontaktowany maksymalnie raz na 90 dni niezależnie od kampanii.
                </div>
            </div>

            <!-- Create New Campaign -->
            <div class="section">
                <div class="section-header">
                    <h2 class="section-title">Utwórz nową kampanię</h2>
                    <p class="section-subtitle">Wypełnij poniższe pola, aby utworzyć kampanię z zaawansowanymi filtrami</p>
                </div>

                <form id="campaignForm" onsubmit="createCampaign(event)">
                    <!-- Basic Info -->
                    <div class="form-grid">
                        <div class="form-group">
                            <label class="form-label" for="campaignName">Nazwa kampanii *</label>
                            <input type="text" id="campaignName" class="form-input" 
                                   placeholder="np. Kraków - Mieszkania Premium" required>
                        </div>

                        <div class="form-group">
                            <label class="form-label" for="checkInterval">Sprawdzaj ostatnie (dni) *</label>
                            <input type="number" id="checkInterval" class="form-input" 
                                   value="1" min="1" max="30" required>
                        </div>
                    </div>

                    <!-- Location Filters -->
                    <div class="filter-section">
                        <div class="filter-section-title">📍 Filtry lokalizacji</div>
                        
                        <div class="form-grid">
                            <div class="form-group">
                                <label class="form-label" for="voivodeship">Województwo *</label>
                                <select id="voivodeship" class="form-select" required>
                                    <option value="">-- Wybierz województwo --</option>
                                    <option value="malopolskie">Małopolskie</option>
                                    <option value="mazowieckie">Mazowieckie</option>
                                    <option value="dolnoslaskie">Dolnośląskie</option>
                                    <option value="wielkopolskie">Wielkopolskie</option>
                                    <option value="slaskie">Śląskie</option>
                                    <option value="pomorskie">Pomorskie</option>
                                    <option value="lodzkie">Łódzkie</option>
                                    <option value="lubelskie">Lubelskie</option>
                                    <option value="podkarpackie">Podkarpackie</option>
                                    <option value="zachodniopomorskie">Zachodniopomorskie</option>
                                    <option value="warminsko_mazurskie">Warmińsko-mazurskie</option>
                                    <option value="kujawsko_pomorskie">Kujawsko-pomorskie</option>
                                    <option value="podlaskie">Podlaskie</option>
                                    <option value="lubuskie">Lubuskie</option>
                                    <option value="swietokrzyskie">Świętokrzyskie</option>
                                    <option value="opolskie">Opolskie</option>
                                </select>
                            </div>

                            <div class="form-group">
                                <label class="form-label" for="county">Powiat (opcjonalnie)</label>
                                <input type="text" id="county" class="form-input" 
                                       placeholder="np. krakowski">
                                <div class="form-hint">Zostaw puste dla całego województwa</div>
                            </div>

                            <div class="form-group">
                                <label class="form-label" for="city">Miasto (opcjonalnie)</label>
                                <input type="text" id="city" class="form-input" 
                                       placeholder="np. Kraków">
                            </div>
                        </div>
                    </div>

                    <!-- Market & Issuer Filters -->
                    <div class="filter-section">
                        <div class="filter-section-title">🏢 Rodzaj oferty</div>
                        
                        <div class="form-grid">
                            <div class="form-group">
                                <label class="form-label" for="issuerType">Typ ogłoszeniodawcy *</label>
                                <select id="issuerType" class="form-select" required>
                                    <option value="REAL_ESTATE_AGENCY">Biuro nieruchomości</option>
                                    <option value="PRIVATE">Osoba prywatna</option>
                                    <option value="DEVELOPER">Deweloper</option>
                                </select>
                            </div>

                            <div class="form-group">
                                <label class="form-label" for="marketType">Rodzaj rynku</label>
                                <select id="marketType" class="form-select">
                                    <option value="">-- Wszystkie --</option>
                                    <option value="SECONDARY">Rynek wtórny</option>
                                    <option value="PRIMARY">Rynek pierwotny</option>
                                </select>
                            </div>
                        </div>

                        <div class="checkbox-group">
                            <input type="checkbox" id="onlyActive" checked>
                            <label for="onlyActive">Tylko aktywne oferty</label>
                        </div>

                        <div class="checkbox-group">
                            <input type="checkbox" id="onlyUnique" checked>
                            <label for="onlyUnique">Tylko unikalne oferty (bez duplikatów)</label>
                        </div>
                    </div>

                    <!-- Price Filters -->
                    <div class="filter-section">
                        <div class="filter-section-title">💰 Filtry cenowe</div>
                        
                        <div class="form-group">
                            <label class="form-label">Cena całkowita (PLN)</label>
                            <div class="range-group">
                                <input type="number" id="minPrice" class="form-input" 
                                       placeholder="Min (np. 300000)" step="10000">
                                <input type="number" id="maxPrice" class="form-input" 
                                       placeholder="Max (np. 1000000)" step="10000">
                            </div>
                        </div>

                        <div class="form-group">
                            <label class="form-label">Cena za m² (PLN/m²)</label>
                            <div class="range-group">
                                <input type="number" id="minPricePerMeter" class="form-input" 
                                       placeholder="Min (np. 5000)" step="100">
                                <input type="number" id="maxPricePerMeter" class="form-input" 
                                       placeholder="Max (np. 15000)" step="100">
                            </div>
                        </div>
                    </div>

                    <!-- Property Filters -->
                    <div class="filter-section">
                        <div class="filter-section-title">📐 Parametry nieruchomości</div>
                        
                        <div class="form-group">
                            <label class="form-label">Powierzchnia (m²)</label>
                            <div class="range-group">
                                <input type="number" id="minArea" class="form-input" 
                                       placeholder="Min (np. 40)" step="5">
                                <input type="number" id="maxArea" class="form-input" 
                                       placeholder="Max (np. 120)" step="5">
                            </div>
                        </div>

                        <div class="form-group">
                            <label class="form-label">Liczba pokoi</label>
                            <div class="range-group">
                                <input type="number" id="minRooms" class="form-input" 
                                       placeholder="Min (np. 2)" min="1" max="10">
                                <input type="number" id="maxRooms" class="form-input" 
                                       placeholder="Max (np. 4)" min="1" max="10">
                            </div>
                        </div>
                    </div>

                    <!-- Sender Selection -->
                    <div class="form-group full-width">
                        <label class="form-label">Wybierz konto nadawcy SMS *</label>
                        <div class="sender-grid" id="senderGrid"></div>
                    </div>

                    <!-- SMS Text -->
                    <div class="form-group full-width">
                        <label class="form-label" for="smsText">Treść wiadomości SMS *</label>
                        <textarea id="smsText" class="form-textarea" 
                                  placeholder="Dzien dobry, jestem z agencji nieruchomosci..." required></textarea>
                        <div class="form-hint">Używaj tylko znaków ASCII (bez polskich znaków). Maksymalnie 160 znaków.</div>
                    </div>

                    <div id="campaignResult"></div>

                    <button type="submit" class="btn btn-success">Utwórz kampanię</button>
                </form>
            </div>

            <!-- Active Campaigns -->
            <div class="section">
                <div class="section-header">
                    <h2 class="section-title">Aktywne kampanie</h2>
                    <p class="section-subtitle">Lista wszystkich kampanii SMS w systemie</p>
                </div>
                <div id="campaignsList" class="campaign-grid"></div>
            </div>

            <!-- Message History -->
            <div class="section">
                <div class="section-header">
                    <h2 class="section-title">Historia wysłanych SMS</h2>
                    <p class="section-subtitle">Wszystkie wysłane wiadomości (<span id="totalMessages">0</span>)</p>
                </div>
                <div id="messagesList" class="message-list"></div>
            </div>
        </div>
    </div>

    <script>
        const PASSWORD = 'H4ctar3s';

        const SENDER_ACCOUNTS = {
            kasia: { id: 'kasia', name: 'Kasia', phone: '48 530 805 774' },
            gosia: { id: 'gosia', name: 'Gosia', phone: '48 881 475 475' },
            daria: { id: 'daria', name: 'Daria', phone: '48 533 344 257' }
        };

        let state = {
            loggedIn: false,
            selectedSender: 'kasia'
        };

        function init() {
            renderSenderGrid();
            
            document.getElementById('password').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') login();
            });

            setInterval(() => {
                if (state.loggedIn) {
                    updateStats();
                    loadCampaigns();
                    loadMessages();
                }
            }, 30000);
        }

        function login() {
            const password = document.getElementById('password').value;
            if (password === PASSWORD) {
                state.loggedIn = true;
                document.getElementById('loginScreen').classList.add('hidden');
                document.getElementById('mainApp').classList.remove('hidden');
                document.getElementById('loginError').classList.add('hidden');
                document.getElementById('password').value = '';
                updateStats();
                loadCampaigns();
                loadMessages();
            } else {
                document.getElementById('loginError').classList.remove('hidden');
            }
        }

        function logout() {
            state.loggedIn = false;
            document.getElementById('mainApp').classList.add('hidden');
            document.getElementById('loginScreen').classList.remove('hidden');
        }

        function renderSenderGrid() {
            const grid = document.getElementById('senderGrid');
            grid.innerHTML = Object.values(SENDER_ACCOUNTS).map(account => `
                <div class="sender-option ${state.selectedSender === account.id ? 'selected' : ''}"
                     onclick="selectSender('${account.id}')">
                    <div class="sender-name">${account.name}</div>
                    <div class="sender-phone">${account.phone}</div>
                </div>
            `).join('');
        }

        function selectSender(senderId) {
            state.selectedSender = senderId;
            renderSenderGrid();
        }

        async function updateStats() {
            try {
                const response = await fetch('/api/stats');
                const data = await response.json();
                
                document.getElementById('totalCampaigns').textContent = data.active_campaigns || 0;
                document.getElementById('totalSent').textContent = data.total_sent || 0;
                document.getElementById('queueSize').textContent = data.queue_size || 0;
                document.getElementById('workingHoursStatus').textContent = data.working_hours ? 'AKTYWNE' : 'NIEAKTYWNE';
                
                const statusDot = document.getElementById('statusDot');
                const statusText = document.getElementById('statusText');
                
                if (data.working_hours) {
                    statusDot.classList.remove('inactive');
                    statusText.textContent = 'System aktywny';
                } else {
                    statusDot.classList.add('inactive');
                    statusText.textContent = 'Poza godzinami pracy';
                }
            } catch (err) {
                console.error('Error:', err);
            }
        }

        function formatFilters(filters) {
            const parts = [];
            
            if (filters.min_price || filters.max_price) {
                const min = filters.min_price ? `${parseInt(filters.min_price).toLocaleString()} PLN` : 'brak';
                const max = filters.max_price ? `${parseInt(filters.max_price).toLocaleString()} PLN` : 'brak';
                parts.push(`Cena: ${min} - ${max}`);
            }
            
            if (filters.min_area || filters.max_area) {
                const min = filters.min_area || 'brak';
                const max = filters.max_area || 'brak';
                parts.push(`Powierzchnia: ${min} - ${max} m²`);
            }
            
            if (filters.min_rooms || filters.max_rooms) {
                const min = filters.min_rooms || 'brak';
                const max = filters.max_rooms || 'brak';
                parts.push(`Pokoje: ${min} - ${max}`);
            }
            
            if (filters.market_type) {
                const type = filters.market_type === 'PRIMARY' ? 'Rynek pierwotny' : 'Rynek wtórny';
                parts.push(type);
            }
            
            return parts.length > 0 ? parts.join(' • ') : 'Brak dodatkowych filtrów';
        }

        async function loadCampaigns() {
            try {
                const response = await fetch('/api/campaigns');
                const campaigns = await response.json();
                
                const container = document.getElementById('campaignsList');
                
                if (campaigns.length === 0) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-state-text">
                                Brak kampanii. Utwórz pierwszą kampanię powyżej.
                            </div>
                        </div>
                    `;
                    return;
                }
                
                container.innerHTML = campaigns.map(c => `
                    <div class="campaign-card">
                        <div class="campaign-header">
                            <div>
                                <div class="campaign-name">${c.name}</div>
                            </div>
                            <span class="campaign-status ${c.active ? 'active' : 'inactive'}">
                                ${c.active ? 'Aktywna' : 'Nieaktywna'}
                            </span>
                        </div>
                        <div class="campaign-info">
                            <div class="campaign-info-item">
                                <div class="campaign-info-label">Nadawca</div>
                                <div class="campaign-info-value">${c.sender}</div>
                            </div>
                            <div class="campaign-info-item">
                                <div class="campaign-info-label">Lokalizacja</div>
                                <div class="campaign-info-value">${c.location || 'N/A'}</div>
                            </div>
                            <div class="campaign-info-item">
                                <div class="campaign-info-label">Wysłano</div>
                                <div class="campaign-info-value">${c.sent_count || 0} SMS</div>
                            </div>
                        </div>
                        ${c.filter_summary ? `<div class="campaign-filters">📊 Filtry: ${c.filter_summary}</div>` : ''}
                        <div class="campaign-text">${c.sms_text}</div>
                        <div class="campaign-actions">
                            <button class="btn btn-small btn-${c.active ? 'secondary' : 'success'}" 
                                    onclick="toggleCampaign('${c.id}')">
                                ${c.active ? 'Zatrzymaj' : 'Aktywuj'}
                            </button>
                            <button class="btn btn-small btn-primary" onclick="runCampaignNow('${c.id}')">
                                Uruchom teraz
                            </button>
                            <button class="btn btn-small btn-danger" onclick="deleteCampaign('${c.id}')">
                                Usuń
                            </button>
                        </div>
                    </div>
                `).join('');
            } catch (err) {
                console.error('Error:', err);
            }
        }

        async function loadMessages() {
            try {
                const response = await fetch('/api/messages');
                const messages = await response.json();
                
                const container = document.getElementById('messagesList');
                
                document.getElementById('totalMessages').textContent = messages.length;
                
                if (messages.length === 0) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-state-text">
                                Brak wysłanych wiadomości
                            </div>
                        </div>
                    `;
                    return;
                }
                
                container.innerHTML = messages.map(m => `
                    <div class="message-card">
                        <div class="message-header">
                            <div class="message-phone">${m.phone}</div>
                            <div class="message-time">${new Date(m.sent_at * 1000).toLocaleString('pl-PL')}</div>
                        </div>
                        <div class="message-meta">
                            ${m.sender} • ${m.campaign_name || 'N/A'}
                        </div>
                        <div class="message-text">${m.text}</div>
                    </div>
                `).join('');
            } catch (err) {
                console.error('Error:', err);
            }
        }

        async function createCampaign(event) {
            event.preventDefault();
            
            const name = document.getElementById('campaignName').value.trim();
            const smsText = document.getElementById('smsText').value.trim();
            const voivodeship = document.getElementById('voivodeship').value;
            const county = document.getElementById('county').value.trim();
            const city = document.getElementById('city').value.trim();
            const issuerType = document.getElementById('issuerType').value;
            const checkInterval = document.getElementById('checkInterval').value;
            const marketType = document.getElementById('marketType').value;
            const minPrice = document.getElementById('minPrice').value;
            const maxPrice = document.getElementById('maxPrice').value;
            const minPricePerMeter = document.getElementById('minPricePerMeter').value;
            const maxPricePerMeter = document.getElementById('maxPricePerMeter').value;
            const minArea = document.getElementById('minArea').value;
            const maxArea = document.getElementById('maxArea').value;
            const minRooms = document.getElementById('minRooms').value;
            const maxRooms = document.getElementById('maxRooms').value;
            const onlyActive = document.getElementById('onlyActive').checked;
            const onlyUnique = document.getElementById('onlyUnique').checked;
            
            try {
                const response = await fetch('/api/campaigns', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: name,
                        sender: state.selectedSender,
                        sms_text: smsText,
                        voivodeship: voivodeship,
                        county: county,
                        city: city,
                        issuer_type: issuerType,
                        last_n_days: parseInt(checkInterval),
                        market_type: marketType || null,
                        min_price: minPrice || null,
                        max_price: maxPrice || null,
                        min_price_per_meter: minPricePerMeter || null,
                        max_price_per_meter: maxPricePerMeter || null,
                        min_area: minArea || null,
                        max_area: maxArea || null,
                        min_rooms: minRooms || null,
                        max_rooms: maxRooms || null,
                        only_active: onlyActive,
                        only_unique: onlyUnique
                    })
                });
                
                const result = await response.json();
                
                if (result.success) {
                    document.getElementById('campaignResult').innerHTML = `
                        <div class="alert alert-success">Kampania utworzona pomyślnie z zaawansowanymi filtrami</div>
                    `;
                    
                    document.getElementById('campaignForm').reset();
                    state.selectedSender = 'kasia';
                    renderSenderGrid();
                    
                    setTimeout(() => {
                        document.getElementById('campaignResult').innerHTML = '';
                        loadCampaigns();
                        updateStats();
                    }, 2000);
                } else {
                    document.getElementById('campaignResult').innerHTML = `
                        <div class="alert alert-error">Błąd: ${result.error}</div>
                    `;
                }
            } catch (err) {
                alert('Błąd: ' + err.message);
            }
        }

        async function toggleCampaign(campaignId) {
            try {
                const response = await fetch(`/api/campaigns/${campaignId}/toggle`, {
                    method: 'POST'
                });
                const result = await response.json();
                if (result.success) {
                    loadCampaigns();
                    updateStats();
                }
            } catch (err) {
                alert('Błąd: ' + err.message);
            }
        }

        async function deleteCampaign(campaignId) {
            if (!confirm('Czy na pewno chcesz usunąć tę kampanię?')) return;
            
            try {
                const response = await fetch(`/api/campaigns/${campaignId}`, {
                    method: 'DELETE'
                });
                const result = await response.json();
                if (result.success) {
                    loadCampaigns();
                    updateStats();
                }
            } catch (err) {
                alert('Błąd: ' + err.message);
            }
        }

        async function runCampaignNow(campaignId) {
            if (!confirm('Uruchomić kampanię natychmiast?')) return;
            
            try {
                const response = await fetch(`/api/campaigns/${campaignId}/run`, {
                    method: 'POST'
                });
                const result = await response.json();
                alert(result.message || 'Kampania uruchomiona');
                loadCampaigns();
                updateStats();
            } catch (err) {
                alert('Błąd: ' + err.message);
            }
        }

        window.addEventListener('DOMContentLoaded', init);
    </script>
</body>
</html>
"""


class AutomationHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {format % args}")

    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode('utf-8'))
            
        elif self.path == '/api/stats':
            active_count = sum(1 for c in campaigns.values() if c.get('active'))
            stats = {
                'active_campaigns': active_count,
                'total_sent': len(sent_messages),
                'queue_size': len(pending_queue),
                'working_hours': is_working_hours()
            }
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(stats).encode('utf-8'))
            
        elif self.path == '/api/campaigns':
            campaign_list = []
            for cid, c in campaigns.items():
                sender_name = SENDER_ACCOUNTS.get(c.get('sender', 'kasia'), {}).get('name', 'Unknown')
                
                # Build location string
                location_parts = []
                location_filter = c.get('filters', {}).get('location_filter', {})
                if location_filter.get('address_state'):
                    location_parts.append(location_filter['address_state'])
                if location_filter.get('address_county'):
                    location_parts.append(location_filter['address_county'])
                if location_filter.get('address_city'):
                    location_parts.append(location_filter['address_city'])
                
                location = ', '.join(location_parts) if location_parts else 'N/A'
                
                # Build filter summary
                filters = c.get('filters', {})
                filter_parts = []
                
                if filters.get('min_price') or filters.get('max_price'):
                    min_p = f"{int(filters.get('min_price', 0)):,}" if filters.get('min_price') else 'brak'
                    max_p = f"{int(filters.get('max_price', 0)):,}" if filters.get('max_price') else 'brak'
                    filter_parts.append(f"Cena: {min_p}-{max_p} PLN")
                
                if filters.get('min_area') or filters.get('max_area'):
                    filter_parts.append(f"Powierzchnia: {filters.get('min_area', 'brak')}-{filters.get('max_area', 'brak')} m²")
                
                if filters.get('min_rooms') or filters.get('max_rooms'):
                    filter_parts.append(f"Pokoje: {filters.get('min_rooms', 'brak')}-{filters.get('max_rooms', 'brak')}")
                
                if filters.get('market_type'):
                    market = 'Pierwotny' if filters['market_type'] == 'PRIMARY' else 'Wtórny'
                    filter_parts.append(f"Rynek: {market}")
                
                filter_summary = ' • '.join(filter_parts) if filter_parts else None
                
                sent_count = sum(1 for m in sent_messages.values() if m.get('campaign_id') == cid)
                
                campaign_list.append({
                    'id': cid,
                    'name': c.get('name', 'Unnamed'),
                    'active': c.get('active', False),
                    'sender': sender_name,
                    'sms_text': c.get('sms_text', ''),
                    'location': location,
                    'filter_summary': filter_summary,
                    'sent_count': sent_count
                })
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(campaign_list).encode('utf-8'))
            
        elif self.path == '/api/messages':
            message_list = []
            for offer_id, m in sorted(sent_messages.items(), key=lambda x: x[1].get('sent_at', 0), reverse=True):
                campaign = campaigns.get(m.get('campaign_id', ''), {})
                message_list.append({
                    'phone': m.get('phone', ''),
                    'sent_at': m.get('sent_at', 0),
                    'sender': m.get('sender', ''),
                    'text': m.get('text', ''),
                    'campaign_name': campaign.get('name', 'N/A')
                })
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(message_list).encode('utf-8'))
            
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        if self.path == '/api/campaigns':
            try:
                data = json.loads(post_data.decode('utf-8'))
                
                campaign_id = f"campaign_{int(time.time())}"
                
                # Build location filter
                voivodeship = data.get('voivodeship', '')
                location_filter = {
                    "address_country": "Polska",
                    "address_state": VOIVODESHIPS.get(voivodeship, voivodeship)
                }
                
                # Add optional location details
                if data.get('county'):
                    location_filter['address_county'] = data['county']
                
                if data.get('city'):
                    location_filter['address_city'] = data['city']
                
                # Build comprehensive filters
                filters = {
                    'location_filter': location_filter,
                    'last_n_days': data.get('last_n_days', 1),
                    'issuer_type': data.get('issuer_type', 'REAL_ESTATE_AGENCY'),
                    'only_active': data.get('only_active', True),
                    'only_unique': data.get('only_unique', True)
                }
                
                # Add optional filters
                if data.get('market_type'):
                    filters['market_type'] = data['market_type']
                
                if data.get('min_price'):
                    filters['min_price'] = data['min_price']
                if data.get('max_price'):
                    filters['max_price'] = data['max_price']
                
                if data.get('min_price_per_meter'):
                    filters['min_price_per_meter'] = data['min_price_per_meter']
                if data.get('max_price_per_meter'):
                    filters['max_price_per_meter'] = data['max_price_per_meter']
                
                if data.get('min_area'):
                    filters['min_area'] = data['min_area']
                if data.get('max_area'):
                    filters['max_area'] = data['max_area']
                
                if data.get('min_rooms'):
                    filters['min_rooms'] = data['min_rooms']
                if data.get('max_rooms'):
                    filters['max_rooms'] = data['max_rooms']
                
                campaigns[campaign_id] = {
                    'id': campaign_id,
                    'name': data.get('name', ''),
                    'sender': data.get('sender', 'kasia'),
                    'sms_text': data.get('sms_text', ''),
                    'active': True,
                    'filters': filters,
                    'created_at': time.time()
                }
                
                save_state()
                
                result = {'success': True, 'campaign_id': campaign_id}
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(result).encode('utf-8'))
                
            except Exception as e:
                result = {'success': False, 'error': str(e)}
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(result).encode('utf-8'))
                
        elif self.path.startswith('/api/campaigns/') and self.path.endswith('/toggle'):
            campaign_id = self.path.split('/')[3]
            if campaign_id in campaigns:
                campaigns[campaign_id]['active'] = not campaigns[campaign_id].get('active', False)
                save_state()
                result = {'success': True}
            else:
                result = {'success': False, 'error': 'Campaign not found'}
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode('utf-8'))
            
        elif self.path.startswith('/api/campaigns/') and self.path.endswith('/run'):
            campaign_id = self.path.split('/')[3]
            if campaign_id in campaigns:
                threading.Thread(target=process_campaign_offers, args=(campaign_id,), daemon=True).start()
                result = {'success': True, 'message': 'Kampania uruchomiona'}
            else:
                result = {'success': False, 'error': 'Campaign not found'}
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode('utf-8'))
            
        else:
            self.send_response(404)
            self.end_headers()

    def do_DELETE(self):
        if self.path.startswith('/api/campaigns/'):
            campaign_id = self.path.split('/')[3]
            if campaign_id in campaigns:
                del campaigns[campaign_id]
                save_state()
                result = {'success': True}
            else:
                result = {'success': False, 'error': 'Campaign not found'}
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()


def run_server(port=PORT):
    load_state()
    
    scheduler_t = threading.Thread(target=scheduler_thread, daemon=True)
    scheduler_t.start()
    
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, AutomationHandler)
    
    print("=" * 60)
    print("SMS Automation System - Enhanced Version")
    print("=" * 60)
    print(f"Adres: http://localhost:{port}")
    print(f"Hasło: {PASSWORD}")
    print("=" * 60)
    print("Nowe filtry:")
    print("- Rodzaj rynku (pierwotny/wtórny)")
    print("- Zakres cen (min/max)")
    print("- Cena za m² (min/max)")
    print("- Powierzchnia (min/max)")
    print("- Liczba pokoi (min/max)")
    print("- Szczegółowa lokalizacja (powiat, miasto)")
    print("- Tylko aktywne/unikalne oferty")
    print("=" * 60)
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nZamykanie...")
        save_state()
        httpd.shutdown()


if __name__ == '__main__':
    run_server()