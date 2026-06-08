import os
import io
import re
import json
import requests
import anthropic
from flask import Flask, request, jsonify, redirect
from PIL import Image, ImageDraw, ImageFont
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from datetime import datetime, timezone
import pytz

app = Flask(__name__)

RED    = (219, 74,  63)
YELLOW = (255, 201, 39)
BLACK  = (0,   0,   0)
WHITE  = (255, 255, 255)
CREAM  = (245, 230, 200)

YOUTUBE_SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl']
SHEETS_SCOPES  = ['https://www.googleapis.com/auth/spreadsheets']
REDIRECT_URI   = 'https://web-production-2545d.up.railway.app/oauth/callback'

SHEET_TAB = 'QPB Schedule'

# YouTube tags applied to every uploaded episode
VIDEO_TAGS = [
    "Que Pasa Boston", "Qué Pasa Boston", "Boston Latino", "iHeart Podcast",
    "podcast", "bilingual podcast", "Boston", "Latino Boston",
    "Gabriela Salas", "Hispanic Boston"
]


def get_font(size, bold=True):
    try:
        if bold:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()


def resolve_photo(photo_url, youtube_id):
    if photo_url and photo_url.strip():
        url = photo_url.strip()
        if 'drive.google.com' in url:
            file_id = None
            if '/file/d/' in url:
                file_id = url.split('/file/d/')[1].split('/')[0]
            elif 'id=' in url:
                file_id = url.split('id=')[1].split('&')[0]
            if file_id:
                url = f"https://drive.google.com/uc?export=download&id={file_id}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                return Image.open(io.BytesIO(resp.content)).convert("RGB")
        except:
            pass
    if youtube_id and youtube_id.strip():
        for quality in ['maxresdefault', 'hqdefault', 'mqdefault']:
            try:
                url = f"https://img.youtube.com/vi/{youtube_id.strip()}/{quality}.jpg"
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    return Image.open(io.BytesIO(resp.content)).convert("RGB")
            except:
                continue
    return None


def fit_photo(photo_img, target_w, target_h):
    """Center-crop the source image to the target aspect ratio, then resize."""
    pw, ph = photo_img.size
    target_ratio = target_w / target_h
    src_ratio = pw / ph
    if src_ratio > target_ratio:
        # too wide -> crop width
        new_w = int(ph * target_ratio)
        left = (pw - new_w) // 2
        box = (left, 0, left + new_w, ph)
    else:
        # too tall -> crop height
        new_h = int(pw / target_ratio)
        top = (ph - new_h) // 2
        box = (0, top, pw, top + new_h)
    return photo_img.crop(box).resize((target_w, target_h), Image.LANCZOS)


def generate_thumbnail(first_name, last_name, category_tag, topic, photo_img):
    W, H = 1280, 720
    canvas = Image.new("RGB", (W, H), YELLOW)
    draw = ImageDraw.Draw(canvas)
    for x in range(0, W, 26):
        for y in range(0, H, 26):
            draw.ellipse([x-2, y-2, x+2, y+2], fill=(255, 215, 80))
    draw.polygon([(0, 0), (510, 0), (430, H), (0, H)], fill=RED)

    if photo_img:
        photo = fit_photo(photo_img, 490, 700)
        canvas.paste(photo, (10, 20))
    else:
        draw.ellipse([140, 60, 340, 260], fill=(180, 40, 30))
        draw.ellipse([60, 260, 420, 700], fill=(180, 40, 30))

    cx = 560

    # Logo bubble
    bubble_x, bubble_y = cx, 60
    draw.rounded_rectangle([bubble_x, bubble_y, bubble_x+260, bubble_y+80], radius=20, fill=CREAM)
    draw.ellipse([bubble_x+230, bubble_y-18, bubble_x+278, bubble_y+28], fill=RED)
    dot_cx = bubble_x + 254
    dot_cy = bubble_y + 5
    for ox in [-12, 0, 12]:
        draw.ellipse([dot_cx+ox-5, dot_cy-5, dot_cx+ox+5, dot_cy+5], fill=WHITE)
    logo_font_sm = get_font(20)
    logo_font_lg = get_font(26)
    draw.text((bubble_x+14, bubble_y+10), "¿QUE PASA", font=logo_font_sm, fill=BLACK)
    draw.text((bubble_x+14, bubble_y+36), "BOSTON?", font=logo_font_lg, fill=RED)

    # Category tag bar
    tag_font = get_font(20)
    tag_y = bubble_y + 100
    draw.rectangle([cx, tag_y, cx+460, tag_y+46], fill=BLACK)
    draw.text((cx+14, tag_y+10), category_tag.upper(), font=tag_font, fill=YELLOW)

    # Guest name
    name_y = tag_y + 62
    name_size = 90 if max(len(first_name), len(last_name)) <= 8 else 72
    name_font = get_font(name_size)
    draw.text((cx, name_y), first_name.upper(), font=name_font, fill=BLACK)
    second_name_y = name_y + name_size + 6
    draw.text((cx, second_name_y), last_name.upper(), font=name_font, fill=RED)

    # Topic box (placed below the second name line)
    topic_font = get_font(26)
    line_height = 36
    words = topic.split()
    lines = []
    current = ""
    for word in words:
        if len(current + " " + word) <= 35:
            current = (current + " " + word).strip()
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    if not lines:
        lines = [""]

    topic_y = second_name_y + name_size + 30
    topic_height = len(lines) * line_height + 24
    draw.rectangle([cx, topic_y, cx+620, topic_y+topic_height], fill=WHITE)
    draw.rectangle([cx, topic_y, cx+8, topic_y+topic_height], fill=RED)
    for i, line in enumerate(lines):
        draw.text((cx+18, topic_y + 12 + (i * line_height)), line, font=topic_font, fill=BLACK)

    # iHeart badge
    bx, by = W-290, H-76
    draw.rectangle([bx, by, W-30, H-26], fill=RED)
    ih_font_sm = get_font(14)
    ih_font_lg = get_font(22)
    draw.text((bx+50, by+8),  "iHEART",   font=ih_font_sm, fill=WHITE)
    draw.text((bx+50, by+26), "PODCASTS", font=ih_font_lg, fill=WHITE)
    draw.ellipse([bx+8, by+8, bx+28, by+28], fill=WHITE)
    draw.ellipse([bx+18, by+8, bx+38, by+28], fill=WHITE)
    draw.polygon([(bx+8, by+20), (bx+23, by+46), (bx+38, by+20)], fill=WHITE)

    draw.rectangle([0, H-12, W, H], fill=YELLOW)
    return canvas


def generate_content_with_claude(first_name, last_name, organization, notes, category_tag):
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    prompt = f"""You are the content writer for Qué Pasa Boston, a premier bilingual iHeartMedia podcast hosted by Gabriela Salas, serving the Hispanic/Latino community and Boston area listeners.

Generate a YouTube title and description for this episode:
- Guest: {first_name} {last_name}
- Organization/Role: {organization}
- Category: {category_tag}
- Key talking points: {notes}

Rules for the TITLE:
- Maximum 70 characters
- Must be engaging and SEO-friendly
- Can be bilingual (mix Spanish/English naturally)
- Include guest name
- No clickbait, just compelling and clear

Rules for the DESCRIPTION:
- 150-200 words
- First paragraph in English (2-3 sentences about the episode)
- Second paragraph in Spanish (same content, translated naturally)
- Include 3-5 relevant hashtags at the end
- Hashtags must include: #QuePasaBoston #iHeartPodcasts #Boston
- Warm, community-focused tone

Return ONLY valid JSON in this exact format:
{{
  "title": "your title here",
  "description": "your full description here"
}}"""
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = message.content[0].text.strip()
    # Be tolerant of markdown code fences around the JSON
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    result = json.loads(raw)
    return result['title'], result['description']


def get_youtube_client():
    creds_json = os.environ.get('YOUTUBE_CREDENTIALS')
    if not creds_json:
        return None
    creds_data = json.loads(creds_json)
    creds = Credentials(
        token=creds_data['token'],
        refresh_token=creds_data['refresh_token'],
        token_uri='https://oauth2.googleapis.com/token',
        client_id=os.environ.get('GOOGLE_CLIENT_ID'),
        client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
        scopes=YOUTUBE_SCOPES
    )
    return build('youtube', 'v3', credentials=creds)


def get_sheets_client():
    creds_json = os.environ.get('GOOGLE_SHEETS_CREDENTIALS')
    if not creds_json:
        return None
    creds_data = json.loads(creds_json)
    creds = ServiceAccountCredentials.from_service_account_info(creds_data, scopes=SHEETS_SCOPES)
    return build('sheets', 'v4', credentials=creds)


def upload_thumbnail(youtube, video_id, thumb_bytes):
    media = MediaIoBaseUpload(io.BytesIO(thumb_bytes), mimetype='image/png', resumable=True)
    youtube.thumbnails().set(videoId=video_id, media_body=media).execute()


def update_video(youtube, video_id, title, description, air_date_str):
    eastern = pytz.timezone('America/New_York')
    try:
        naive_dt = datetime.strptime(air_date_str, '%m/%d/%Y %I:%M %p')
    except:
        try:
            naive_dt = datetime.strptime(air_date_str, '%m/%d/%Y %H:%M')
        except:
            # Date only: default to the standing 8:30am Sunday release time
            naive_dt = datetime.strptime(air_date_str, '%m/%d/%Y').replace(hour=8, minute=30)
    local_dt = eastern.localize(naive_dt)
    utc_dt = local_dt.astimezone(timezone.utc)
    publish_at = utc_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    video_response = youtube.videos().list(part='snippet,status', id=video_id).execute()
    if not video_response['items']:
        raise Exception(f"Video {video_id} not found on YouTube")
    video = video_response['items'][0]
    video['snippet']['title'] = title
    video['snippet']['description'] = description
    video['snippet']['categoryId'] = '22'
    video['snippet']['tags'] = VIDEO_TAGS
    video['status']['privacyStatus'] = 'private'
    video['status']['publishAt'] = publish_at
    youtube.videos().update(
        part='snippet,status',
        body={'id': video_id, 'snippet': video['snippet'], 'status': video['status']}
    ).execute()
    return f"https://www.youtube.com/watch?v={video_id}"


def run_pipeline(first_name, last_name, organization, notes, category_tag,
                 photo_url, youtube_id, air_date):
    """Full pipeline for a single episode. Returns (title, description, video_url)."""
    photo_img = resolve_photo(photo_url, youtube_id)
    topic = notes[:60] if notes else f"{first_name} {last_name} on Qué Pasa Boston"
    thumb_canvas = generate_thumbnail(first_name, last_name, category_tag, topic, photo_img)

    title, description = generate_content_with_claude(
        first_name, last_name, organization, notes, category_tag
    )

    buf = io.BytesIO()
    thumb_canvas.save(buf, format='PNG')
    thumb_bytes = buf.getvalue()

    video_url = f"https://www.youtube.com/watch?v={youtube_id}"
    youtube = get_youtube_client()
    if youtube and youtube_id:
        upload_thumbnail(youtube, youtube_id, thumb_bytes)
        video_url = update_video(youtube, youtube_id, title, description, air_date)

    return title, description, video_url


# ---------------------------------------------------------------------------
# Google Sheets batch helpers
# ---------------------------------------------------------------------------

def sheet_get_rows(sheets, spreadsheet_id):
    resp = sheets.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{SHEET_TAB}'!A2:L"
    ).execute()
    return resp.get('values', [])


def sheet_update_cell(sheets, spreadsheet_id, column, row_number, value):
    sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{SHEET_TAB}'!{column}{row_number}",
        valueInputOption='RAW',
        body={'values': [[value]]}
    ).execute()


def cell(row, idx):
    return row[idx].strip() if idx < len(row) and row[idx] is not None else ''


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'QPB Agent is running!',
        'version': '3.0',
        'anthropic_ready': bool(os.environ.get('ANTHROPIC_API_KEY')),
        'google_ready': bool(os.environ.get('GOOGLE_CLIENT_ID')),
        'youtube_authorized': bool(os.environ.get('YOUTUBE_CREDENTIALS')),
        'sheets_ready': bool(os.environ.get('GOOGLE_SHEETS_CREDENTIALS')),
        'spreadsheet_configured': bool(os.environ.get('SPREADSHEET_ID')),
    })


@app.route('/authorize', methods=['GET'])
def authorize():
    flow = Flow.from_client_config(
        {"web": {"client_id": os.environ.get('GOOGLE_CLIENT_ID'), "client_secret": os.environ.get('GOOGLE_CLIENT_SECRET'), "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": [REDIRECT_URI]}},
        scopes=YOUTUBE_SCOPES, redirect_uri=REDIRECT_URI
    )
    auth_url, _ = flow.authorization_url(access_type='offline', include_granted_scopes='true', prompt='consent')
    return redirect(auth_url)


@app.route('/oauth/callback', methods=['GET'])
def oauth_callback():
    flow = Flow.from_client_config(
        {"web": {"client_id": os.environ.get('GOOGLE_CLIENT_ID'), "client_secret": os.environ.get('GOOGLE_CLIENT_SECRET'), "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": [REDIRECT_URI]}},
        scopes=YOUTUBE_SCOPES, redirect_uri=REDIRECT_URI
    )
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    creds_data = {'token': creds.token, 'refresh_token': creds.refresh_token, 'token_uri': creds.token_uri, 'client_id': creds.client_id, 'client_secret': creds.client_secret, 'scopes': list(creds.scopes) if creds.scopes else []}
    return f"""<html><body style="font-family:sans-serif;max-width:600px;margin:50px auto;text-align:center;">
    <h2>✅ YouTube Authorization Successful!</h2>
    <textarea style="width:100%;height:200px;font-size:11px;padding:10px;">{json.dumps(creds_data)}</textarea>
    </body></html>"""


@app.route('/process', methods=['POST'])
def process_episode():
    try:
        data = request.get_json()
        first_name   = data.get('first_name', '')
        last_name    = data.get('last_name', '')
        organization = data.get('organization', '')
        notes        = data.get('notes', '')
        category_tag = data.get('category_tag', 'ENTREVISTA · INTERVIEW')
        photo_url    = data.get('photo_url', '')
        youtube_id   = data.get('youtube_id', '')
        air_date     = data.get('air_date', '')

        title, description, video_url = run_pipeline(
            first_name, last_name, organization, notes, category_tag,
            photo_url, youtube_id, air_date
        )
        return jsonify({
            'success': True,
            'title': title,
            'description': description,
            'video_url': video_url,
            'message': f'✅ Episode processed: {first_name} {last_name}'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/batch', methods=['POST', 'GET'])
def batch_process():
    """Process every row in the sheet whose Thumbnail Status (col K) == 'Pending'."""
    spreadsheet_id = os.environ.get('SPREADSHEET_ID')
    sheets = get_sheets_client()
    if not sheets:
        return jsonify({'success': False, 'error': 'GOOGLE_SHEETS_CREDENTIALS not configured'}), 500
    if not spreadsheet_id:
        return jsonify({'success': False, 'error': 'SPREADSHEET_ID not configured'}), 500

    try:
        rows = sheet_get_rows(sheets, spreadsheet_id)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Failed to read sheet: {e}'}), 500

    results = []
    processed = 0

    # Column letters: I=Generated Title, J=Generated Description, K=Status, L=Result
    for i, row in enumerate(rows):
        row_number = i + 2  # data starts at row 2
        status = cell(row, 10)  # column K
        if status.lower() != 'pending':
            continue

        first_name   = cell(row, 0)   # A
        last_name    = cell(row, 1)   # B
        organization = cell(row, 2)   # C
        notes        = cell(row, 3)   # D
        air_date     = cell(row, 4)   # E
        category_tag = cell(row, 5) or 'ENTREVISTA · INTERVIEW'  # F
        photo_url    = cell(row, 6)   # G
        youtube_id   = cell(row, 7)   # H

        # Mark as Processing immediately so a concurrent run won't double-process
        try:
            sheet_update_cell(sheets, spreadsheet_id, 'K', row_number, 'Processing')
        except Exception as e:
            results.append({'row': row_number, 'status': 'Error', 'error': f'status write failed: {e}'})
            continue

        try:
            title, description, video_url = run_pipeline(
                first_name, last_name, organization, notes, category_tag,
                photo_url, youtube_id, air_date
            )
            sheet_update_cell(sheets, spreadsheet_id, 'I', row_number, title)
            sheet_update_cell(sheets, spreadsheet_id, 'J', row_number, description)
            sheet_update_cell(sheets, spreadsheet_id, 'K', row_number, 'Done')
            sheet_update_cell(sheets, spreadsheet_id, 'L', row_number, video_url)
            processed += 1
            results.append({
                'row': row_number,
                'guest': f'{first_name} {last_name}',
                'status': 'Done',
                'title': title,
                'video_url': video_url
            })
        except Exception as e:
            err = str(e)
            try:
                sheet_update_cell(sheets, spreadsheet_id, 'K', row_number, 'Error')
                sheet_update_cell(sheets, spreadsheet_id, 'L', row_number, err[:500])
            except:
                pass
            results.append({
                'row': row_number,
                'guest': f'{first_name} {last_name}',
                'status': 'Error',
                'error': err
            })

    return jsonify({
        'success': True,
        'processed': processed,
        'total_pending': len(results),
        'results': results,
        'message': f'✅ Batch complete: {processed} processed'
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
