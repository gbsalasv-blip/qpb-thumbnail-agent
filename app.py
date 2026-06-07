import os
import io
import json
import requests
import anthropic
from flask import Flask, request, jsonify, redirect
from PIL import Image, ImageDraw, ImageFont
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from datetime import datetime, timezone
import pytz

app = Flask(__name__)

# ── BRAND COLORS ──
RED    = (219, 74,  63)
YELLOW = (255, 201, 39)
BLACK  = (0,   0,   0)
WHITE  = (255, 255, 255)
CREAM  = (245, 230, 200)

SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl']
REDIRECT_URI = 'https://web-production-2545d.up.railway.app/oauth/callback'

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

def generate_thumbnail(first_name, last_name, category_tag, topic, photo_img):
    W, H = 1280, 720
    canvas = Image.new("RGB", (W, H), YELLOW)
    draw = ImageDraw.Draw(canvas)
    for x in range(0, W, 26):
        for y in range(0, H, 26):
            draw.ellipse([x-2, y-2, x+2, y+2], fill=(255, 215, 80))
    draw.polygon([(0,0),(510,0),(430,H),(0,H)], fill=RED)
    if photo_img:
        photo = photo_img.resize((490, 700), Image.LANCZOS)
        pw, ph = photo.size
        if pw > ph:
            left = (pw - ph) // 2
            photo = photo.crop([left, 0, left+ph, ph])
            photo = photo.resize((490, 700), Image.LANCZOS)
        canvas.paste(photo, (10, 20))
    else:
        draw.ellipse([140, 60, 340, 260], fill=(180, 40, 30))
        draw.ellipse([60, 260, 420, 700], fill=(180, 40, 30))
    cx = 560
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
    tag_font = get_font(20)
    tag_y = bubble_y + 100
    draw.rectangle([cx, tag_y, cx+460, tag_y+46], fill=BLACK)
    draw.text((cx+14, tag_y+10), category_tag.upper(), font=tag_font, fill=YELLOW)
    name_y = tag_y + 62
    name_size = 90 if max(len(first_name), len(last_name)) <= 8 else 72
    name_font = get_font(name_size)
    draw.text((cx, name_y), first_name.upper(), font=name_font, fill=BLACK)
    draw.text((cx, name_y + name_size + 6), last_name.upper(), font=name_font, fill=RED)
    topic_y = name_y + (name_size * 2) + 30
    topic_font = get_font(26)
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
    topic_height = len(lines) * 36 + 24
    draw.rectangle([cx, topic_y, cx+620, topic_y+topic_height], fill=(255,255,255,180))
    draw.rectangle([cx, topic_y, cx+8, topic_y+topic_height], fill=RED)
    for i, line in enumerate(lines):
        draw.text((cx+18, topic_y+12+(i*36)), line, font=topic_font, fill=BLACK)
    bx, by = W-290, H-76
    draw.rectangle([bx, by, W-30, H-26], fill=RED)
    ih_font_sm = get_font(14)
    ih_font_lg = get_font(22)
    draw.text((bx+50, by+8),  "iHEART",   font=ih_font_sm, fill=WHITE)
    draw.text((bx+50, by+26), "PODCASTS", font=ih_font_lg, fill=WHITE)
    draw.ellipse([bx+8, by+8, bx+28, by+28], fill=WHITE)
    draw.ellipse([bx+18, by+8, bx+38, by+28], fill=WHITE)
    draw.polygon([(bx+8,by+20),(bx+23,by+46),(bx+38,by+20)], fill=WHITE)
    draw.rectangle([0, H-12, W, H], fill=YELLOW)
    return canvas

def generate_content_with_claude(first_name, last_name, organization, notes, category_tag):
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    prompt = f"""You are the content writer for Qué Pasa Boston, a premier bilingual iHeartMedia podcast 
hosted by Gabriela Salas, serving the Hispanic/Latino community and Boston area listeners.

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
    result = json.loads(message.content[0].text)
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
        scopes=SCOPES
    )
    return build('youtube', 'v3', credentials=creds)

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
            naive_dt = datetime.strptime(air_date_str, '%m/%d/%Y')
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
    video['status']['privacyStatus'] = 'private'
    video['status']['publishAt'] = publish_at
    youtube.videos().update(
        part='snippet,status',
        body={'id': video_id, 'snippet': video['snippet'], 'status': video['status']}
    ).execute()
    return f"https://www.youtube.com/watch?v={video_id}"

# ── ROUTES ──

@app.route('/health', methods=['GET'])
def health():
    has_anthropic = bool(os.environ.get('ANTHROPIC_API_KEY'))
    has_google    = bool(os.environ.get('GOOGLE_CLIENT_ID'))
    has_youtube   = bool(os.environ.get('YOUTUBE_CREDENTIALS'))
    return jsonify({
        'status': 'QPB Agent is running!',
        'version': '2.0',
        'anthropic_ready': has_anthropic,
        'google_ready': has_google,
        'youtube_authorized': has_youtube
    })

@app.route('/authorize', methods=['GET'])
def authorize():
    """Step 1: Send Gaby to Google to authorize YouTube access"""
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": os.environ.get('GOOGLE_CLIENT_ID'),
                "client_secret": os.environ.get('GOOGLE_CLIENT_SECRET'),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [REDIRECT_URI]
            }
        },
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    return redirect(auth_url)

@app.route('/oauth/callback', methods=['GET'])
def oauth_callback():
    """Step 2: Google redirects back here with the auth code"""
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": os.environ.get('GOOGLE_CLIENT_ID'),
                "client_secret": os.environ.get('GOOGLE_CLIENT_SECRET'),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [REDIRECT_URI]
            }
        },
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    creds_data = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': list(creds.scopes) if creds.scopes else []
    }
    return f"""
    <html><body style="font-family:sans-serif;max-width:600px;margin:50px auto;text-align:center;">
    <h2>✅ YouTube Authorization Successful!</h2>
    <p>Copy the credentials below and add them to Railway as <strong>YOUTUBE_CREDENTIALS</strong></p>
    <textarea style="width:100%;height:200px;font-size:11px;padding:10px;">{json.dumps(creds_data)}</textarea>
    <p><strong>Next step:</strong> Go to Railway → Variables → New Variable<br>
    Name: <code>YOUTUBE_CREDENTIALS</code><br>Value: paste the JSON above</p>
    </body></html>
    """

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

        photo_img = resolve_photo(photo_url, youtube_id)
        thumb_canvas = generate_thumbnail(
            first_name, last_name, category_tag,
            notes[:60] if notes else f"{first_name} {last_name} on Qué Pasa Boston",
            photo_img
        )
        title, description = generate_content_with_claude(
            first_name, last_name, organization, notes, category_tag
        )
        thumb_bytes = io.BytesIO()
        thumb_canvas.save(thumb_bytes, format='PNG')
        thumb_bytes = thumb_bytes.getvalue()

        video_url = f"https://www.youtube.com/watch?v={youtube_id}"
        youtube = get_youtube_client()
        if youtube and youtube_id:
            upload_thumbnail(youtube, youtube_id, thumb_bytes)
            video_url = update_video(youtube, youtube_id, title, description, air_date)

        return jsonify({
            'success': True,
            'title': title,
            'description': description,
            'video_url': video_url,
            'message': f'✅ Episode processed: {first_name} {last_name}'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
