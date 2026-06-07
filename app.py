import os
import io
import json
import requests
import anthropic
from flask import Flask, request, jsonify
from PIL import Image, ImageDraw, ImageFont
from google.oauth2.credentials import Credentials
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

def get_font(size, bold=True):
    """Load font with fallback"""
    try:
        if bold:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()

def resolve_photo(photo_url, youtube_id):
    """Get best available guest photo"""
    # Priority 1: Direct photo URL or Google Drive link
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

    # Priority 2: YouTube thumbnail frame
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
    """Generate QPB branded thumbnail 1280x720"""
    W, H = 1280, 720
    canvas = Image.new("RGB", (W, H), YELLOW)
    draw = ImageDraw.Draw(canvas)

    # Halftone dots on yellow background
    for x in range(0, W, 26):
        for y in range(0, H, 26):
            draw.ellipse([x-2, y-2, x+2, y+2], fill=(255, 215, 80))

    # Left red diagonal strip
    draw.polygon([(0,0),(510,0),(430,H),(0,H)], fill=RED)

    # Guest photo (left zone)
    if photo_img:
        photo = photo_img.resize((490, 700), Image.LANCZOS)
        # Crop to portrait if wider than tall
        pw, ph = photo.size
        if pw > ph:
            left = (pw - ph) // 2
            photo = photo.crop([left, 0, left+ph, ph])
            photo = photo.resize((490, 700), Image.LANCZOS)
        canvas.paste(photo, (10, 20))
    else:
        # No photo - draw silhouette placeholder
        draw.ellipse([140, 60, 340, 260], fill=(180, 40, 30))
        draw.ellipse([60, 260, 420, 700], fill=(180, 40, 30))

    # ── RIGHT CONTENT PANEL ──
    cx = 560  # left edge of content zone

    # QPB Speech bubble badge
    bubble_x, bubble_y = cx, 60
    draw.rounded_rectangle([bubble_x, bubble_y, bubble_x+260, bubble_y+80],
                           radius=20, fill=CREAM)
    # Dot bubble accent
    draw.ellipse([bubble_x+230, bubble_y-18, bubble_x+278, bubble_y+28], fill=RED)
    dot_cx = bubble_x + 254
    dot_cy = bubble_y + 5
    for ox in [-12, 0, 12]:
        draw.ellipse([dot_cx+ox-5, dot_cy-5, dot_cx+ox+5, dot_cy+5], fill=WHITE)

    # Logo text in bubble
    logo_font_sm = get_font(20)
    logo_font_lg = get_font(26)
    draw.text((bubble_x+14, bubble_y+10), "¿QUE PASA", font=logo_font_sm, fill=BLACK)
    draw.text((bubble_x+14, bubble_y+36), "BOSTON?", font=logo_font_lg, fill=RED)

    # Category tag pill
    tag_font = get_font(20)
    tag_y = bubble_y + 100
    draw.rectangle([cx, tag_y, cx+460, tag_y+46], fill=BLACK)
    draw.text((cx+14, tag_y+10), category_tag.upper(), font=tag_font, fill=YELLOW)

    # Guest name - FIRST (black) then LAST (red)
    name_y = tag_y + 62
    # Scale font size based on name length
    name_size = 90 if max(len(first_name), len(last_name)) <= 8 else 72
    name_font = get_font(name_size)
    draw.text((cx, name_y), first_name.upper(), font=name_font, fill=BLACK)
    draw.text((cx, name_y + name_size + 6), last_name.upper(), font=name_font, fill=RED)

    # Topic subtitle box
    topic_y = name_y + (name_size * 2) + 30
    topic_font = get_font(26)
    # Word wrap topic at ~35 chars
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

    # iHeart badge bottom-right
    bx, by = W-290, H-76
    draw.rectangle([bx, by, W-30, H-26], fill=RED)
    ih_font_sm = get_font(14)
    ih_font_lg = get_font(22)
    draw.text((bx+50, by+8),  "iHEART",   font=ih_font_sm, fill=WHITE)
    draw.text((bx+50, by+26), "PODCASTS", font=ih_font_lg, fill=WHITE)
    # Heart shape
    draw.ellipse([bx+8, by+8, bx+28, by+28], fill=WHITE)
    draw.ellipse([bx+18, by+8, bx+38, by+28], fill=WHITE)
    draw.polygon([(bx+8,by+20),(bx+23,by+46),(bx+38,by+20)], fill=WHITE)

    # Yellow bottom bar
    draw.rectangle([0, H-12, W, H], fill=YELLOW)

    return canvas

def generate_content_with_claude(first_name, last_name, organization, notes, category_tag):
    """Use Claude to generate title and description"""
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
- Include 3-5 relevant hashtags at the end (mix Spanish/English)
- Hashtags must include: #QuePasaBoston #iHeartPodcasts #Boston
- Warm, community-focused tone

Return ONLY valid JSON in this exact format, nothing else:
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

def upload_thumbnail_to_youtube(youtube_id, thumbnail_bytes, credentials_json):
    """Upload thumbnail image to YouTube video"""
    creds_data = json.loads(credentials_json)
    creds = Credentials(
        token=creds_data['token'],
        refresh_token=creds_data['refresh_token'],
        token_uri='https://oauth2.googleapis.com/token',
        client_id=creds_data['client_id'],
        client_secret=creds_data['client_secret']
    )
    youtube = build('youtube', 'v3', credentials=creds)
    media = MediaIoBaseUpload(
        io.BytesIO(thumbnail_bytes),
        mimetype='image/png',
        resumable=True
    )
    youtube.thumbnails().set(
        videoId=youtube_id,
        media_body=media
    ).execute()

def update_youtube_video(youtube_id, title, description, air_date_str, credentials_json):
    """Update YouTube video title, description and schedule publish time"""
    creds_data = json.loads(credentials_json)
    creds = Credentials(
        token=creds_data['token'],
        refresh_token=creds_data['refresh_token'],
        token_uri='https://oauth2.googleapis.com/token',
        client_id=creds_data['client_id'],
        client_secret=creds_data['client_secret']
    )
    youtube = build('youtube', 'v3', credentials=creds)

    # Parse air date and convert to Eastern → UTC for YouTube API
    eastern = pytz.timezone('America/New_York')
    try:
        naive_dt = datetime.strptime(air_date_str, '%m/%d/%Y %I:%M %p')
    except:
        naive_dt = datetime.strptime(air_date_str, '%m/%d/%Y %H:%M')
    local_dt = eastern.localize(naive_dt)
    utc_dt = local_dt.astimezone(timezone.utc)
    publish_at = utc_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Get current video details
    video_response = youtube.videos().list(
        part='snippet,status',
        id=youtube_id
    ).execute()

    if not video_response['items']:
        raise Exception(f"Video {youtube_id} not found")

    video = video_response['items'][0]
    snippet = video['snippet']
    snippet['title'] = title
    snippet['description'] = description
    snippet['categoryId'] = '22'  # People & Blogs

    # Schedule for Sunday 8:30am EST
    status = video['status']
    status['privacyStatus'] = 'private'
    status['publishAt'] = publish_at

    youtube.videos().update(
        part='snippet,status',
        body={
            'id': youtube_id,
            'snippet': snippet,
            'status': status
        }
    ).execute()

    return f"https://www.youtube.com/watch?v={youtube_id}"

# ── FLASK ROUTES ──

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'QPB Agent is running!', 'version': '1.0'})

@app.route('/process', methods=['POST'])
def process_episode():
    """Main endpoint - receives episode data, generates thumbnail, updates YouTube"""
    try:
        data = request.get_json()

        first_name    = data.get('first_name', '')
        last_name     = data.get('last_name', '')
        organization  = data.get('organization', '')
        notes         = data.get('notes', '')
        category_tag  = data.get('category_tag', 'ENTREVISTA · INTERVIEW')
        photo_url     = data.get('photo_url', '')
        youtube_id    = data.get('youtube_id', '')
        air_date      = data.get('air_date', '')
        credentials   = data.get('youtube_credentials', '')

        # Step 1: Get guest photo
        photo_img = resolve_photo(photo_url, youtube_id)

        # Step 2: Generate thumbnail
        thumb_canvas = generate_thumbnail(
            first_name, last_name, category_tag,
            notes[:50] if notes else f"{first_name} {last_name} on Qué Pasa Boston",
            photo_img
        )

        # Step 3: Generate title + description with Claude
        title, description = generate_content_with_claude(
            first_name, last_name, organization, notes, category_tag
        )

        # Step 4: Upload thumbnail to YouTube
        thumb_bytes = io.BytesIO()
        thumb_canvas.save(thumb_bytes, format='PNG')
        thumb_bytes = thumb_bytes.getvalue()

        if youtube_id and credentials:
            upload_thumbnail_to_youtube(youtube_id, thumb_bytes, credentials)
            video_url = update_youtube_video(youtube_id, title, description, air_date, credentials)
        else:
            video_url = f"https://www.youtube.com/watch?v={youtube_id}"

        return jsonify({
            'success': True,
            'title': title,
            'description': description,
            'video_url': video_url,
            'message': f'✅ Episode processed for {first_name} {last_name}'
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
