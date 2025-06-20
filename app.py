import os
from datetime import datetime
from flask import Flask, request, redirect, url_for, render_template, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from jinja2 import DictLoader
from pyngrok import ngrok
from moviepy.editor import VideoFileClip  # Ensure moviepy is installed (pip install moviepy)
from flask import jsonify
from sqlalchemy import or_, and_



# Set your ngrok authtoken
ngrok.set_auth_token("2tmGFhW6OOOomrk0n0UIQJzUq5U_4Nur9EZXNMbpD8GArqVi")

# Initialize app and config
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret-key'  # Change this in production
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///social.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
# Update ALLOWED_EXTENSIONS to include audio types
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov', 'mp3', 'wav', 'ogg'}


db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Association table for followers
followers = db.Table('followers',
    db.Column('follower_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('followed_id', db.Integer, db.ForeignKey('user.id'))
)

# Association table for likes
likes = db.Table('likes',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('post_id', db.Integer, db.ForeignKey('post.id'))
)

# FollowRequest model
class FollowRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    target_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    requester = db.relationship("User", foreign_keys=[requester_id])
    target = db.relationship("User", foreign_keys=[target_id])

# User model
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(150), nullable=False)
    is_private = db.Column(db.Boolean, default=False)  # False = Public, True = Private
    profile_pic = db.Column(db.String(200), nullable=True)  # New: for profile picture
    bio = db.Column(db.Text, nullable=True)
    dm_keypass = db.Column(db.String(150), nullable=True)
    posts = db.relationship('Post', backref='author', lazy=True)
    comments = db.relationship('Comment', backref='author', lazy=True)
    followed = db.relationship(
        'User', secondary=followers,
        primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        backref=db.backref('followers', lazy='dynamic'), lazy='dynamic'
    )
    liked_posts = db.relationship('Post', secondary=likes,
                                  backref=db.backref('liked_by', lazy='dynamic'),
                                  lazy='dynamic')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# Post model
class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=True)
    media_filename = db.Column(db.String(200), nullable=True)
    video_thumbnail = db.Column(db.String(200), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)  # For reposts/replies
    reposts = db.relationship('Post', backref=db.backref('parent', remote_side=[id]), lazy='dynamic')
    comments = db.relationship('Comment', backref='post', lazy=True)
    pinned = db.Column(db.Boolean, default=False)
    comments_enabled = db.Column(db.Boolean, default=True)
    like_count_visible = db.Column(db.Boolean, default=True)
    archived = db.Column(db.Boolean, default=False)
    is_repost = db.Column(db.Boolean, default=False)  # NEW: marks reposts
    deleted = db.Column(db.Boolean, default=False)
    deleted_at = db.Column(db.DateTime, nullable=True)



# Updated Comment model with recursive relationship and media support
class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    media_filename = db.Column(db.String(200), nullable=True)  # New: for images/videos in comments
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=True)  # For recursive comments
    children = db.relationship('Comment', backref=db.backref('parent', remote_side=[id]), lazy=True)

class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    participant1_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    participant2_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category = db.Column(db.String(20))  # "primary" or "general"
    dm_pending = db.Column(db.Boolean)  # For DM requests
    # Remove the existing global "hidden" flag and add per-user hidden state:
    # hidden = db.Column(db.Boolean, default=False)
    hidden_by = db.Column(db.String, default="")  # e.g., "3,5" means users with IDs 3 and 5 have hidden this convo.
    pinned = db.Column(db.Boolean, default=False)
    muted = db.Column(db.Boolean, default=False)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = db.relationship('Message', backref='conversation', lazy=True)

    @property
    def participant1(self):
        return User.query.get(self.participant1_id)

    @property
    def participant2(self):
        return User.query.get(self.participant2_id)



class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversation.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)




@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# -----------------------
# Templates via DictLoader
# -----------------------

base_template = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Social Media App</title>
  <style>
  @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: 'Roboto', sans-serif;
  background-color: #fafafa;  /* light background */
  color: #262626;  /* dark grey text */
  padding-bottom: 70px; /* for bottom nav */
}

/* Header */
header {
  position: fixed;
  top: 0;
  width: 100%;
  background: #fff;
  border-bottom: 1px solid #dbdbdb;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 20px;
  z-index: 1000;
}


.header-right .icon {
  font-size: 1.5rem;
  color: #262626;
  margin-left: 15px;
}

.header-right .icon:hover {
  color: #0095f6;
}


/* Container */
.container {
  max-width: 935px;  /* similar to Instagram's max width */
  margin: 80px auto 20px; /* account for fixed header */
  padding: 0 20px;
}

/* Bottom Navigation */
.bottom-nav {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: #fff;
  border-top: 1px solid #dbdbdb;
  display: flex;
  justify-content: space-around;
  padding: 10px 0;
  z-index: 1000;
}

.bottom-nav a {
  color: #262626;
  text-decoration: none;
  font-size: 3rem;
  font-weight: 500;
}


.bottom-nav {
  display: flex;
  justify-content: space-around;
  background: white;
  border-top: 1px solid #dbdbdb;
  position: fixed;
  bottom: 0;
  width: 100%;
  padding: 10px 0;
}

.bottom-nav a {
  text-decoration: none;
  color: #262626;
  font-size: 1.5rem;
}

.bottom-nav a:hover {
  color: #0095f6;
}




/* Cards */
.card {
  background: #fff;
  border: 1px solid #dbdbdb;
  border-radius: 3px;
  margin-bottom: 20px;
  padding: 20px;
  transition: transform 0.3s ease;
}

.card:hover {
  transform: translateY(-3px);
}

/* Card Header */
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  position: relative;
}

.card-header h3 {
  font-size: 1rem;
  font-weight: 500;
  margin: 0;
  color: #262626;
}

/* Fallback styling for card-actions */
.card-actions {
  display: flex;
  justify-content: space-between;
  margin-top: 10px;
  border-top: 1px solid #eee;
}

.card-actions .action-btn {
  flex: 1;
  text-align: center;
  padding: 10px 0;
  text-decoration: none;
  color: #fff;
  background: #0095f6; /* Instagram-like blue */
  border-right: 1px solid #eee;
  transition: background 0.3s ease;
}

.card-actions .action-btn:hover {
  background: #8e8e8e;
}

.card-actions .action-btn:last-child {
  border-right: none;
}

.card-profile-pic {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
  border: 1px solid #dbdbdb;
}

.enhanced-post-card {
  border: 1px solid #dbdbdb;
  border-radius: 3px;
  background: #fff;
  margin-bottom: 20px;
  overflow: hidden;
  font-family: 'Roboto', sans-serif;
}

/* Enhanced Post Card Header */
.enhanced-post-card .card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 15px;
}

.enhanced-post-card .author-info {
  display: flex;
  align-items: center;
}

.enhanced-post-card .card-profile-pic {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
  margin-right: 10px;
  border: 1px solid #dbdbdb;
}

.enhanced-post-card .author-username {
  font-weight: 600;
  color: #262626;
  text-decoration: none;
}

/* Enhanced Post Card Media */
.enhanced-post-card .card-media img,
.enhanced-post-card .card-media video {
  width: 100%;
  display: block;
}

/* Enhanced Post Card Actions */
.enhanced-post-card .card-actions {
  display: flex;
  justify-content: space-around;
  padding: 8px 0;
  border-top: 1px solid #efefef;
}

/* Updated Action Buttons for Enhanced Post Card */
.enhanced-post-card .action-btn {
  flex: 1;
  text-align: center;
  padding: 10px 0;
  text-decoration: none;
  color: #262626; /* default dark grey */
  font-size: 20px; /* icon size */
  background: transparent;
  border: none;
  transition: color 0.3s ease;
}

.enhanced-post-card .action-btn:hover {
  color: #000; /* hover turns black */
}

/* Ensure liked like button stays red even on hover */
.enhanced-post-card .action-btn.like-btn.liked {
  color: #000; /* liked heart in Instagram red */
}
.enhanced-post-card .action-btn.like-btn.liked:hover {
  color: #000;
}

/* Enhanced Post Card Caption */
.enhanced-post-card .card-caption {
  padding: 10px 15px;
  font-size: 14px;
  color: #262626;
}

.enhanced-post-card .likes-count {
  font-weight: 600;
  display: block;
  margin-bottom: 5px;
}

/* Enhanced Post Card Footer */
.enhanced-post-card .card-footer {
  padding: 5px 15px;
  font-size: 12px;
  color: #8e8e8e;
}

/* Post Options Dropdown */
.post-options {
  position: relative;
}

.dropbtn {
  background: transparent;
  border: none;
  font-size: 1.2rem;
  cursor: pointer;
}

.dropdown-content {
  display: none;
  position: absolute;
  right: 0;
  top: 100%;
  background: #fff;
  min-width: 160px;
  box-shadow: 0 5px 15px rgba(0,0,0,0.1);
  border-radius: 3px;
  z-index: 1000;
}

.dropdown-content a {
  color: #262626;
  padding: 10px 15px;
  text-decoration: none;
  display: block;
  font-size: 0.9rem;
  border-bottom: 1px solid #efefef;
}

.dropdown-content a:last-child {
  border-bottom: none;
}

.dropdown-content a:hover {
  background: #fafafa;
}

.dropdown-content.show {
  display: block;
}

/* Card Content */
.card-content p {
  margin-bottom: 10px;
  font-size: 0.9rem;
  line-height: 1.4;
}

.card-content img,
.card-content video {
  max-width: 100%;
  border-radius: 3px;
  margin-top: 10px;
}

/* Profile Navigation */
.profile-nav {
  margin: 15px 0;
  border-bottom: 1px solid #dbdbdb;
  display: flex;
}

.profile-nav a {
  padding: 10px 15px;
  text-decoration: none;
  color: #262626;
  font-weight: 500;
}

.profile-nav a.active {
  border-bottom: 1px solid #262626;
}

/* Profile Grid (for user posts) */
.profile-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(25%, 1fr));
  grid-gap: 10px;
  margin-top: 20px;
}
.profile-grid img {
  width: 100%;
  object-fit: cover;
}

/* Grid Items Styling */
.profile-grid .grid-item {
  display: block;
  background: #fff;
  border: 1px solid #dbdbdb;
  border-radius: 3px;
  overflow: hidden;
  text-decoration: none;
  color: inherit;
}

/* Image Posts Span More Rows for a Larger Look */
.profile-grid .grid-item.image-post {
  grid-row: span 2;
}
.profile-grid .grid-item.image-post img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

/* Text Posts are Smaller and Centered */
.profile-grid .grid-item.text-post {
  grid-row: span 1;
  background: #fafafa;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 10px;
  font-size: 14px;
  text-align: center;
  overflow: hidden;
}

.video-thumbnail-container {
  position: relative;
  width: 100%;
  height: 100%;
}

.video-thumbnail-container img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.video-play-icon {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 2em;
  color: rgba(255, 255, 255, 0.9);
  text-shadow: 0 0 10px rgba(0, 0, 0, 0.5);
}

/* Forms */
form {
  background: #fff;
  padding: 20px;
  border-radius: 3px;
  margin-bottom: 20px;
}

form input[type="text"],
form input[type="email"],
form input[type="password"],
form textarea {
  width: 100%;
  padding: 10px;
  margin: 10px 0;
  border: 1px solid #dbdbdb;
  border-radius: 3px;
  font-size: 0.9rem;
}

form input[type="submit"] {
  background: #0095f6;
  color: #fff;
  border: none;
  padding: 10px 15px;
  border-radius: 3px;
  cursor: pointer;
  font-size: 0.9rem;
  transition: background 0.3s ease;
}

form input[type="submit"]:hover {
  background: #007ac1;
}

/* Alerts */
.alert {
  background: #ed4956;
  color: #fff;
  padding: 15px;
  border-radius: 3px;
  margin-bottom: 20px;
  text-align: center;
}

/* Search Box */
.search-container {
  max-width: 600px;
  margin: auto;
  text-align: center;
  padding: 20px;
}

.search-box {
  display: flex;
  align-items: center;
  background: #f0f0f0;
  border-radius: 25px;
  padding: 8px 12px;
  margin-bottom: 20px;
}

.search-box input {
  flex-grow: 1;
  border: none;
  background: transparent;
  padding: 10px;
  font-size: 1rem;
  outline: none;
}

.search-box button {
  background: transparent;
  border: none;
  font-size: 1.2rem;
  cursor: pointer;
  color: #333;
}

.search-box button:hover {
  color: #0095f6;
}

.search-results {
  list-style: none;
  padding: 0;
}

.search-results li {
  display: flex;
  align-items: center;
  padding: 10px;
  border-bottom: 1px solid #ddd;
}

.search-results li a {
  display: flex;
  align-items: center;
  text-decoration: none;
  color: #333;
  width: 100%;
  padding: 10px;
  transition: background 0.3s;
}

.search-results li a:hover {
  background: #f9f9f9;
}

.search-results img {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  margin-right: 10px;
}


/* Footer */
footer {
  text-align: center;
  padding: 15px;
  background: #fff;
  color: #262626;
  border-top: 1px solid #dbdbdb;
  margin-top: 20px;
}

/* Responsive */
@media (max-width: 768px) {
  .header-left h1 {
    font-size: 1.3rem;
  }
  .bottom-nav a {
    font-size: 0.8rem;
  }
}

/* ---------- Comments Section Styling ---------- */
.comment {
  background: #fff;
  border: 1px solid #dbdbdb;
  border-radius: 3px;
  padding: 10px;
  margin-bottom: 10px;
}

.comment-header {
  display: flex;
  align-items: center;
  margin-bottom: 5px;
}

.comment-profile-pic {
  width: 30px;
  height: 30px;
  border-radius: 50%; /* ensures circular profile pic */
  object-fit: cover;
  margin-right: 8px;
  border: 1px solid #dbdbdb;
}

.comment-author {
  font-weight: 600;
  color: #262626;
  margin-right: 10px;
  text-decoration: none;
  font-size: 0.9rem;
}

.comment-date {
  font-size: 0.75rem;
  color: #8e8e8e;
}

.comment-body {
  margin-bottom: 5px;
  font-size: 0.9rem;
  line-height: 1.3;
}

.comment-actions {
  margin-top: 5px;
}

.reply-btn {
  font-size: 0.8rem;
  color: #007ac1;
  text-decoration: none;
  transition: color 0.3s ease;
}

.reply-btn:hover {
  color: #005f8c;
}

.profile-tabs .tab {
  flex: 1;
  text-align: center;
  padding: 12px 0;
  border-bottom: 2px solid transparent;
  font-size: 1.2rem;
  transition: border-color 0.3s;
}
.profile-tabs .tab.active {
  border-bottom: 2px solid #262626;
  color: #262626;
}

.recommendations-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 16px;
  margin-top: 20px;
}

.recommendation-item {
  text-align: center;
  padding: 10px;
  background: #fff;
  border: 1px solid #dbdbdb;
  border-radius: 8px;
  transition: transform 0.2s ease;
}

.recommendation-item:hover {
  transform: scale(1.03);
}

.recommendation-item img {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  object-fit: cover;
  margin-bottom: 8px;
}

.recommendation-item p {
  font-size: 0.9rem;
  font-weight: 500;
  color: #262626;
  margin: 0;
}

/* Modal Popup Styles */
.modal {
  display: none;
  position: fixed;
  z-index: 10000;
  left: 0;
  top: 0;
  width: 100%;
  height: 100%;
  overflow: auto;
  background-color: rgba(0,0,0,0.8);
  padding-top: 60px;
}
.modal-content {
  background-color: #fff;
  margin: 5% auto;
  padding: 20px;
  border: 1px solid #888;
  width: 90%;
  max-width: 900px;
  border-radius: 8px;
  position: relative;
}
.modal .close {
  color: #aaa;
  position: absolute;
  top: 10px;
  right: 20px;
  font-size: 28px;
  font-weight: bold;
  cursor: pointer;
}
.modal .close:hover,
.modal .close:focus {
  color: #000;
}

/* Overlay for multiple media */
.multiple-overlay {
  position: absolute;
  bottom: 8px;
  right: 8px;
  background: rgba(0,0,0,0.6);
  border-radius: 50%;
  padding: 4px;
  color: #fff;
  font-size: 12px;
}

/* Video Thumbnail Overlay */
.video-thumbnail-container {
  position: relative;
}
.video-play-icon {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 2em;
  color: rgba(255, 255, 255, 0.9);
  text-shadow: 0 0 10px rgba(0, 0, 0, 0.5);
}

/* Grid Item Styling */
.profile-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(25%, 1fr));
  gap: 10px;
  margin-top: 20px;
}
.profile-grid .grid-item {
  position: relative;
  display: block;
  text-decoration: none;
  color: inherit;
  overflow: hidden;
  border: 1px solid #dbdbdb;
  border-radius: 3px;
}
.profile-grid .grid-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

/* Dark Theme Styles */
/* ----------------- Dark Theme Overrides ----------------- */
/* ----------------- Dark Theme Overrides ----------------- */
body.dark {
  background-color: #181818;
  color: #e0e0e0;
}

/* Header & Navigation */
body.dark header {
  background: #242424;
  border-bottom: 1px solid #333;
}
body.dark header h1 {
  color: #e0e0e0;
}
body.dark .header-right .icon,
body.dark #dark-mode-toggle {
  color: #e0e0e0;
}
body.dark .header-right .icon:hover,
body.dark #dark-mode-toggle:hover {
  color: #0095f6;
}
body.dark .container {
  background-color: #181818;
}
body.dark nav.bottom-nav {
  background: #242424;
  border-top: 1px solid #333;
}
body.dark .bottom-nav a {
  color: #e0e0e0;
}
body.dark .bottom-nav a:hover {
  color: #0095f6;
}
body.dark footer {
  background: #242424;
  border-top: 1px solid #333;
  color: #e0e0e0;
}

/* Cards & Post Details */
body.dark .card,
body.dark .enhanced-post-card {
  background: #242424;
  border: 1px solid #333;
}
body.dark .card-header h3,
body.dark .enhanced-post-card .author-username,
body.dark .enhanced-post-card .card-caption,
body.dark .enhanced-post-card .card-footer,
body.dark .card-content p,
body.dark .enhanced-post-card .card-caption p {
  color: #e0e0e0;
}
body.dark .card-actions .action-btn {
  color: #e0e0e0;
}
body.dark .card-actions .action-btn:hover {
  color: #fff;
}

/* Dropdowns */
body.dark .dropdown-content {
  background: #242424;
  border: 1px solid #333;
}
body.dark .dropdown-content a {
  color: #e0e0e0;
}
body.dark .dropdown-content a:hover {
  background: #333;
}

/* Profile & Tabs */
body.dark .profile-nav a {
  color: #e0e0e0;
}
body.dark .profile-nav a.active {
  border-bottom: 1px solid #e0e0e0;
}
body.dark .profile-tabs .tab {
  color: #e0e0e0 !important;
}
body.dark .profile-tabs .tab i {
  color: #e0e0e0 !important;
}
body.dark .profile-grid .grid-item {
  background: #242424;
  border: 1px solid #333;
}
body.dark .profile-grid .grid-item.text-post {
  background: #181818;
  color: #e0e0e0;
}

/* New overrides for profile email and comment usernames */
body.dark .profile-bio {
  color: #e0e0e0 !important;
}
body.dark .comments-list a {
  color: #e0e0e0 !important;
}

/* Slider */
body.dark .slider-btn {
  background: rgba(255, 255, 255, 0.3);
  color: #e0e0e0;
}
body.dark .slider-dots span {
  background: rgba(224, 224, 224, 0.7);
}
body.dark .slider-dots span.active {
  background: #e0e0e0;
}

/* Forms (New Post, Profile Settings, Comment, etc.) */
body.dark form {
  background: #242424;
}
body.dark form input[type="text"],
body.dark form input[type="email"],
body.dark form input[type="password"],
body.dark form textarea {
  background: #181818;
  border: 1px solid #333;
  color: #e0e0e0;
}
body.dark form input[type="text"]::placeholder,
body.dark form input[type="email"]::placeholder,
body.dark form input[type="password"]::placeholder,
body.dark form textarea::placeholder {
  color: #aaa;
}
body.dark form input[type="submit"] {
  background: #0095f6;
  color: #fff;
}

/* Alerts */
body.dark .alert {
  background: #d32f2f;
}

/* Search Box */
body.dark .search-box {
  background: #333;
}
body.dark .search-box input {
  color: #e0e0e0;
}
body.dark .search-box button {
  color: #e0e0e0;
}
body.dark .search-results li a {
  color: #e0e0e0;
}

/* Comments Section */
body.dark .comment {
  background: #242424;
  border: 1px solid #333;
  color: #e0e0e0;
}
body.dark .comment-header .comment-author {
  color: #e0e0e0;
}
body.dark .comment-date {
  color: #aaa;
}
body.dark .comment-body {
  color: #e0e0e0;
}

/* Override dropbtn (⋮) color */
body.dark .dropbtn {
  color: #e0e0e0 !important;
}

/* Override new-post-container background, border, and text color */
body.dark .new-post-container {
  background: #242424 !important;
  border: 1px solid #242424 !important;
  color: #e0e0e0 !important;
}

/* Floating Comment Form in Dark Mode */
body.dark .floating-comment-form {
  background: #242424 !important;
  border-top: 1px solid #242424 !important;
  color: #e0e0e0 !important;
}

body.dark .floating-comment-form input[type="text"] {
  background: #181818 !important;
  border: 1px solid #242424 !important;
  color: #e0e0e0 !important;
}

body.dark .floating-comment-form label {
  color: #3897f0 !important;
}

body.dark .floating-comment-form button {
  color: #3897f0 !important;
  background: none !important;
  border: none !important;
}

body.dark .floating-comment-form .replying-to {
  background: #242424 !important;
  border: 1px solid #242424 !important;
  color: #e0e0e0 !important;
}

body.dark .floating-comment-form .replying-to a {
  color: #3897f0 !important;
}

/* Dark Mode for Search Recommendations */
body.dark .recommendations-grid {
  /* Optionally, you can change the background of the grid container if needed */
  background-color: transparent;
}

body.dark .recommendation-item {
  background: #242424 !important;
  border: 1px solid #333 !important;
}

body.dark .recommendation-item p {
  color: #e0e0e0 !important;
}

/* ---------- Dark Mode Overrides for Modal, Grid, and Form ---------- */
body.dark .modal {
  background-color: rgba(0, 0, 0, 0.6);
  padding-top: 60px;
}
body.dark .modal-content {
  background-color: #181818;
  margin: 5% auto;
  padding: 20px;
  border: 1px solid #333;
  width: 90%;
  max-width: 900px;
  border-radius: 8px;
  position: relative;
  color: #e0e0e0;
}
body.dark .modal .close {
  color: #ccc;
  top: 10px;
  right: 20px;
  font-size: 28px;
  font-weight: bold;
  cursor: pointer;
}
body.dark .modal .close:hover,
body.dark .modal .close:focus {
  color: #fff;
}
body.dark .multiple-overlay {
  background: rgba(0, 0, 0, 0.8);
  color: #e0e0e0;
}
body.dark .video-thumbnail-container {
  position: relative;
}
body.dark .video-play-icon {
  color: rgba(224, 224, 224, 0.9);
  text-shadow: 0 0 10px rgba(0, 0, 0, 0.8);
}
body.dark .profile-grid {
  grid-template-columns: repeat(auto-fill, minmax(25%, 1fr));
  gap: 10px;
  margin-top: 20px;
}
body.dark .profile-grid .grid-item {
  border: 1px solid #444;
  background-color: #242424;
}
body.dark .profile-grid .grid-item img {
  object-fit: cover;
}

/* Dark Mode Overrides for Settings Form and Media Buttons */
body.dark .settings-form form {
  background: #242424 !important;
  border: 1px solid #333 !important;
  color: #e0e0e0 !important;
}

body.dark .settings-form form label,
body.dark .settings-form form input[type="submit"],
body.dark .settings-form form input[type="file"] {
  color: #e0e0e0 !important;
}

body.dark .settings-tabs button {
  background: #242424 !important;
  border: 1px solid #333 !important;
  color: #e0e0e0 !important;
}

body.dark .dm-view-container {
  background-color: #242424 !important;
  border: 1px solid #333 !important;
  color: #e0e0e0 !important;
  box-shadow: 0 2px 5px rgba(0,0,0,0.1) !important;
}

body.dark .dm-header {
  background-color: #181818 !important;
  border-bottom: 1px solid #333 !important;
}

body.dark .dm-header h2 {
  color: #e0e0e0 !important;
}

body.dark .dm-messages {
  background-color: #181818 !important;
  color: #e0e0e0 !important;
}

body.dark .dm-messages .dm-message.sent .message-content {
  background-color: #3897f0 !important;
  color: #fff !important;
}

body.dark .dm-messages .dm-message.received .message-content {
  background-color: #333 !important;
  color: #e0e0e0 !important;
}

body.dark .dm-messages .message-timestamp {
  color: #aaa !important;
}

body.dark .dm-input {
  background-color: #181818 !important;
  border-top: 1px solid #333 !important;
}

body.dark .dm-input input[type="text"] {
  background-color: #2a2a2a !important;
  border: 1px solid #333 !important;
  color: #e0e0e0 !important;
}

body.dark .dm-input button {
  background-color: #0095f6 !important;
  color: #fff !important;
  border: none !important;
}

/* Modal full-window styles */
#postModal {
  display: none;
  position: fixed;
  z-index: 10000;
  left: 0;
  top: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0,0,0,0.8);
}
#postModalContent {
  position: relative;
  margin: 5% auto;
  width: 90%;
  max-width: 900px;
  animation: slideIn 0.5s ease;
}
@keyframes slideIn {
  from { transform: translateY(100%); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}

/* Full Window Modal Content: make it a scroll snap container */
#postModalContent {
  height: 100vh;
  overflow-y: scroll;
  scroll-snap-type: y mandatory;
}

/* Each full-window post fills the viewport and snaps into view */
.enhanced-post-card {
  scroll-snap-align: start;
  overflow-y: auto; /* in case the post content overflows */
}

/* Audio Visualization Styles */
.audio-visualization {
  background: #f7f7f7;
  border: 1px solid #ddd;
  border-radius: 10px;
  padding: 8px;
  margin: 10px 0;
  cursor: pointer;
  display: flex;
  align-items: center;
}
.audio-controls {
  display: flex;
  align-items: center;
  width: 100%;
}
.audio-play-icon {
  font-size: 18px;
  margin-right: 10px;
  color: #555;
  transition: color 0.2s ease;
}
.audio-slider {
  flex-grow: 1;
  margin-right: 10px;
  -webkit-appearance: none;
  appearance: none;
  height: 4px;
  border-radius: 2px;
  background: #ddd;
  outline: none;
}
.audio-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #555;
  cursor: pointer;
  transition: background 0.2s ease;
}
.audio-duration {
  font-size: 14px;
  color: #555;
}
.audio-visualization:hover .audio-play-icon {
  color: #000;
}


  </style>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
</head>
<body>
  <header>
    <div class="header-left">
      <h1>Social Media App</h1>
    </div>
    <div class="header-right">
      {% if current_user.is_authenticated %}
        <a href="{{ url_for('follow_requests') }}" class="icon" title="Follow Requests"><i class="fas fa-bell"></i></a>
        <a href="{{ url_for('logout') }}" class="icon">Logout</a>
      {% endif %}
      <!-- Dark Mode Toggle Button -->
      <button id="dark-mode-toggle" title="Toggle Dark Mode" style="background: none; border: none; cursor: pointer; font-size: 1.5rem; margin-left: 15px;">
        <i class="fas fa-moon"></i>
      </button>
    </div>
  </header>
  <div class="container">
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        <div class="alert">
          {% for message in messages %}
            <p>{{ message }}</p>
          {% endfor %}
        </div>
      {% endif %}
    {% endwith %}
    {% block content %}{% endblock %}
  </div>
  <nav class="bottom-nav">
    {% if current_user.is_authenticated %}
<nav class="bottom-nav">
  {% if current_user.is_authenticated %}
    <nav class="bottom-nav">
      <a href="{{ url_for('index') }}" title="Home"><i class="fas fa-home"></i></a>
      <a href="{{ url_for('for_you') }}" title="For You"><i class="fas fa-compass"></i></a>
      <a href="{{ url_for('search') }}" title="Search"><i class="fas fa-search"></i></a>
      <a href="{{ url_for('new_post') }}" title="New Post"><i class="fas fa-plus-square"></i></a>
      <a href="{{ url_for('dm_inbox') }}" title="Direct Messages"><i class="fas fa-paper-plane"></i></a>
      <a href="{{ url_for('profile', username=current_user.username) }}" title="Profile"><i class="fas fa-user"></i></a>
    </nav>
  {% endif %}
</nav>

    {% endif %}
  </nav>
  <footer>
    <p>&copy; 2025 Social Media App</p>
  </footer>

  <script>
    function toggleDropdown(button) {
      var dropdown = button.nextElementSibling;
      dropdown.classList.toggle("show");
    }
    window.onclick = function(e) {
      if (!e.target.matches('.dropbtn')) {
        var dropdowns = document.getElementsByClassName("dropdown-content");
        for (var i = 0; i < dropdowns.length; i++) {
          var openDropdown = dropdowns[i];
          if (openDropdown.classList.contains('show')) {
            openDropdown.classList.remove('show');
          }
        }
      }
    }
  </script>

  <script>
    document.addEventListener('DOMContentLoaded', function(){
      document.querySelectorAll('.like-btn').forEach(function(button) {
        button.addEventListener('click', function(e) {
          e.preventDefault();
          const url = this.href;
          const likeBtn = this;
          fetch(url, {
            headers: {
              'X-Requested-With': 'XMLHttpRequest'
            }
          })
          .then(response => response.json())
          .then(data => {
            const card = likeBtn.closest('.card');
            if(card){
              const likesCountElem = card.querySelector('.likes-count');
              if(likesCountElem) {
                likesCountElem.textContent = data.likes + ' likes';
              }
            }
            if(data.liked){
              likeBtn.innerHTML = '<i class="fas fa-heart"></i>';
              likeBtn.href = url.replace('like', 'unlike');
            } else {
              likeBtn.innerHTML = '<i class="far fa-heart"></i>';
              likeBtn.href = url.replace('unlike', 'like');
            }
          })
          .catch(error => console.error('Error:', error));
        });
      });
    });
  </script>

  <!-- Dark Mode Toggle Script -->
  <script>
    // Check local storage for dark mode setting on page load
    if (localStorage.getItem('darkMode') === 'enabled') {
      document.body.classList.add('dark');
    }
    
    const darkModeToggle = document.getElementById('dark-mode-toggle');
    darkModeToggle.addEventListener('click', function() {
      document.body.classList.toggle('dark');
      // Save preference to localStorage
      if (document.body.classList.contains('dark')) {
        localStorage.setItem('darkMode', 'enabled');
      } else {
        localStorage.setItem('darkMode', 'disabled');
      }
    });
  </script>

  <!-- Existing Slider CSS & JS (unchanged) -->
  <style>
    /* Slider CSS */
    .media-slider {
      position: relative;
      overflow: hidden;
      border-radius: 4px;
      width: 100%;
      display: flex;
      justify-content: center;
      align-items: center;
    }
    .slider-wrapper {
      display: flex;
      transition: transform 0.5s ease-in-out;
      align-items: center;
    }
    .slide {
      min-width: 100%;
      display: flex;
      justify-content: center;
      align-items: center;
    }
    .slide img,
    .slide video {
      width: auto;
      max-width: 100%;
      height: auto;
      display: block;
      max-height: 90vh;
    }
    .slider-btn {
      position: absolute;
      top: 50%;
      transform: translateY(-50%);
      background: rgba(0,0,0,0.4);
      border: none;
      color: #fff;
      width: 40px;
      height: 40px;
      border-radius: 50%;
      cursor: pointer;
      z-index: 10;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 20px;
    }
    .slider-btn.prev { left: 10px; }
    .slider-btn.next { right: 10px; }
    .slider-dots {
      position: absolute;
      bottom: 10px;
      width: 100%;
      text-align: center;
    }
    .slider-dots span {
      display: inline-block;
      width: 8px;
      height: 8px;
      margin: 0 4px;
      background: rgba(255, 255, 255, 0.7);
      border-radius: 50%;
      cursor: pointer;
    }
    .slider-dots span.active {
      background: rgba(255, 255, 255, 1);
    }
  </style>
  <script>
    document.addEventListener('DOMContentLoaded', function(){
      document.querySelectorAll('.media-slider').forEach(function(slider) {
        let currentIndex = 0;
        const wrapper = slider.querySelector('.slider-wrapper');
        const slides = slider.querySelectorAll('.slide');
        const dotsContainer = slider.querySelector('.slider-dots');

        function updateSlider() {
          wrapper.style.transform = 'translateX(' + (-currentIndex * 100) + '%)';
          Array.from(dotsContainer.children).forEach((dot, idx) => {
            dot.classList.toggle('active', idx === currentIndex);
          });
          const currentSlide = slides[currentIndex];
          const mediaElement = currentSlide.querySelector('img, video');
          if (mediaElement) {
            const newHeight = mediaElement.clientHeight;
            slider.style.height = newHeight + 'px';
          }
        }
        setTimeout(() => updateSlider(), 100);
        slider.querySelector('.slider-btn.next').addEventListener('click', function(){
          currentIndex = (currentIndex + 1) % slides.length;
          updateSlider();
        });
        slider.querySelector('.slider-btn.prev').addEventListener('click', function(){
          currentIndex = (currentIndex - 1 + slides.length) % slides.length;
          updateSlider();
        });
        slides.forEach((slide, idx) => {
          const dot = document.createElement('span');
          dot.addEventListener('click', () => {
            currentIndex = idx;
            updateSlider();
          });
          dotsContainer.appendChild(dot);
        });
        updateSlider();
      });
    });
  </script>

<script>
let offset = 10;
const loadMorePosts = () => {
  fetch(`/load_posts?offset=${offset}`)
    .then(res => res.text())
    .then(html => {
      // Append the new posts to your posts container
      document.querySelector('#postsContainer').insertAdjacentHTML('beforeend', html);
      offset += 10;
      // Reattach the observer to the new 7th-from-last post if needed
      attachObserver();
    });
};

const observerOptions = { threshold: 0.5 };
let observer;

const attachObserver = () => {
  // Remove previous observer if any
  if(observer) observer.disconnect();
  // Assume posts have a class 'post-card'
  const posts = document.querySelectorAll('.post-card');
  if (posts.length >= 7) {
    const target = posts[posts.length - 7];
    observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if(entry.isIntersecting){
          loadMorePosts();
        }
      });
    }, observerOptions);
    observer.observe(target);
  }
};

document.addEventListener('DOMContentLoaded', attachObserver);
</script>







<script>
// Global audio state: true means media are muted (default)
var globalAudioMuted = true;
// Flag to temporarily disable auto-play when the user manually plays a media.
var manualPlay = false;

// Global toggle: clicking any audio toggle button toggles audio for all media.
function toggleGlobalAudio(btn) {
  globalAudioMuted = !globalAudioMuted;
  var mediaElements = document.querySelectorAll('video, audio');
  mediaElements.forEach(function(media) {
    media.muted = globalAudioMuted;
  });
  var toggleButtons = document.querySelectorAll('.audio-toggle');
  toggleButtons.forEach(function(button) {
    button.textContent = globalAudioMuted ? "🔇" : "🔊";
  });
}

// Function to handle manual play for audio via its container.
function playThisAudio(event, container) {
  event.stopPropagation();
  var audio = container.querySelector('audio');
  if (!audio) return;
  manualPlay = true;
  // Pause all media except this one.
  document.querySelectorAll('video, audio').forEach(function(other) {
    if (other !== audio) other.pause();
  });
  audio.play();
  // After 2 seconds, re-enable auto-play via observer.
  setTimeout(() => { manualPlay = false; }, 2000);
}

var currentPlayingCard = null;

function setupPostCardObserver() {
  var postCards = document.querySelectorAll('.enhanced-post-card');
  
  var observer = new IntersectionObserver(function(entries) {
    // For each entry, if it’s at least 90% visible, record the time it became visible.
    entries.forEach(function(entry) {
      if (entry.intersectionRatio >= 0.9) {
        entry.target.dataset.visibleTime = Date.now();
      }
    });
    
    // Get all cards that are at least 90% visible (i.e. have a visibleTime)
    var visibleCards = Array.from(postCards).filter(function(card) {
      return card.dataset.visibleTime;
    });
    
    if (visibleCards.length === 0) {
      // If no card is sufficiently visible, pause the current playing media.
      if (currentPlayingCard) {
        currentPlayingCard.querySelectorAll('video, audio').forEach(function(media) {
          media.pause();
        });
        currentPlayingCard = null;
      }
      return;
    }
    
    // Sort visible cards by the most recent visible time.
    visibleCards.sort(function(a, b) {
      return parseInt(b.dataset.visibleTime) - parseInt(a.dataset.visibleTime);
    });
    
    // The most recently visible card gets priority.
    var newCard = visibleCards[0];
    
    // If the new card is not already playing, switch.
    if (currentPlayingCard !== newCard) {
      if (currentPlayingCard) {
        currentPlayingCard.querySelectorAll('video, audio').forEach(function(media) {
          media.pause();
        });
      }
      newCard.querySelectorAll('video, audio').forEach(function(media) {
        media.play();
      });
      currentPlayingCard = newCard;
    }
    
    // Clean up: Remove the visibleTime data attribute for cards that are less than 90% visible.
    entries.forEach(function(entry) {
      if (entry.intersectionRatio < 0.9) {
        delete entry.target.dataset.visibleTime;
      }
    });
    
  }, { threshold: [0.9] });
  
  postCards.forEach(function(card) {
    observer.observe(card);
  });
}


// Call this function on DOMContentLoaded:
document.addEventListener('DOMContentLoaded', setupPostCardObserver);




// When the DOM is loaded, set up observer and attach click listeners.
document.addEventListener('DOMContentLoaded', function() {
  setupMediaObserver();
  // For video elements, attach click listener.
  document.querySelectorAll('video').forEach(function(media) {
    media.addEventListener('click', function() {
      manualPlay = true;
      document.querySelectorAll('video, audio').forEach(function(other) {
        if (other !== media) other.pause();
      });
      media.play();
      setTimeout(() => { manualPlay = false; }, 2000);
    });
  });
  // For audio, the container (.audio-visualization) already has an onclick="playThisAudio(event, this)".
});
</script>

<style>
.audio-slider {
  width: 100%;
  -webkit-appearance: none;
  appearance: none;
  height: 8px;
  border-radius: 4px;
  background: #e0e0e0;
  outline: none;
  opacity: 0.9;
  transition: opacity 0.2s;
  cursor: pointer;
}
.audio-slider:hover {
  opacity: 1;
}
.audio-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #0095f6;
  cursor: pointer;
  border: 2px solid #fff;
  box-shadow: 0 0 2px rgba(0, 0, 0, 0.5);
}
.audio-slider::-moz-range-thumb {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #0095f6;
  cursor: pointer;
  border: 2px solid #fff;
  box-shadow: 0 0 2px rgba(0, 0, 0, 0.5);
}
</style>



<script>
// Updates the slider's value and background based on the audio's progress.
function updateAudioSlider(audioElement) {
  var slider = audioElement.parentElement.querySelector('.audio-slider');
  if (audioElement.duration) {
    var progressPercent = (audioElement.currentTime / audioElement.duration) * 100;
    slider.value = progressPercent;
    slider.style.background = 'linear-gradient(to right, #0095f6 ' + progressPercent + '%, #e0e0e0 ' + progressPercent + '%)';
  }
}

// Handles clicks on the audio container. If the audio is not playing,
// resets it to the beginning and plays it; and pauses any other media.
function handleAudioClick(container) {
  var audio = container.querySelector('audio');
  if (!audio) return;
  // Pause every other media (videos and audios)
  document.querySelectorAll('video, audio').forEach(function(media) {
    if (media !== audio) media.pause();
  });
  // If the audio is not playing, reset and start it.
  if (audio.paused) {
    audio.currentTime = 0;
    audio.play();
    // Reset the slider
    var slider = container.querySelector('.audio-slider');
    if (slider) {
      slider.value = 0;
      slider.style.background = 'linear-gradient(to right, #0095f6 0%, #e0e0e0 0%)';
    }
  }
}

// When the slider's value changes, seek the audio to the new position.
// Also, pause other media.
function seekAudio(slider) {
  var container = slider.parentElement;
  var audio = container.querySelector('audio');
  if (audio && audio.duration) {
    // Pause other media elements
    document.querySelectorAll('video, audio').forEach(function(media) {
      if (media !== audio) media.pause();
    });
    // Seek to the selected time.
    audio.currentTime = (slider.value / 100) * audio.duration;
    // Resume playback if it was already playing.
    if (audio.paused) {
      audio.play();
    }
  }
}

// Global audio toggle: toggles mute state for all media elements.
var globalAudioMuted = true;
function toggleGlobalAudio(btn) {
  globalAudioMuted = !globalAudioMuted;
  var mediaElements = document.querySelectorAll('video, audio');
  mediaElements.forEach(function(media) {
    media.muted = globalAudioMuted;
  });
  var toggleButtons = document.querySelectorAll('.volume-toggle');
  toggleButtons.forEach(function(button) {
    if (globalAudioMuted) {
      button.innerHTML = '<i class="fas fa-volume-mute"></i>';
    } else {
      button.innerHTML = '<i class="fas fa-volume-up"></i>';
    }
  });
}

</script>





</body>
</html>

"""

# Post card template (used in Home and For You)
# NOTE: The comment button now links to the post detail page.
post_card = """
<div class="card enhanced-post-card">
  <!-- Card Header -->
  <div class="card-header">
    <div class="author-info">
      {% if post.author.profile_pic %}
        <img class="card-profile-pic" src="{{ url_for('static', filename='uploads/' ~ post.author.profile_pic) }}" alt="{{ post.author.username }}'s profile picture">
      {% else %}
        <img class="card-profile-pic" src="{{ url_for('static', filename='uploads/default_profile.png') }}" alt="{{ post.author.username }}'s profile picture">
      {% endif %}
      <a href="{{ url_for('profile', username=post.author.username) }}" class="author-username">
        {{ post.author.username }}
      </a>
    </div>
    {% if current_user.id == post.author.id %}
      <div class="post-options">
        <div class="dropdown">
          <button class="dropbtn" onclick="toggleDropdown(this)">⋮</button>
          <div class="dropdown-content">
            <a href="{{ url_for('delete_post', post_id=post.id) }}">Delete</a>
            <a href="{{ url_for('pin_post', post_id=post.id) }}">
              {{ 'Unpin' if post.pinned else 'Pin' }}
            </a>
            <a href="{{ url_for('edit_post', post_id=post.id) }}">Edit</a>
            <a href="{{ url_for('toggle_comments', post_id=post.id) }}">
              {{ 'Turn On Comments' if not post.comments_enabled else 'Turn Off Comments' }}
            </a>
            <a href="{{ url_for('toggle_like_visibility', post_id=post.id) }}">
              {{ 'Show Like Count' if not post.like_count_visible else 'Hide Like Count' }}
            </a>
            <a href="{{ url_for('archive_post', post_id=post.id) }}">
              {{ 'Unarchive' if post.archived else 'Archive' }}
            </a>
          </div>
        </div>
      </div>
    {% endif %}
  </div>

  {% if post.is_repost %}
    {% if post.parent %}
      <p><strong>{{ post.author.username }}</strong> reposted <strong>{{ post.parent.author.username }}</strong>'s post:</p><br>
    {% else %}
      <p><strong>{{ post.author.username }}</strong> reposted a comment:</p><br>
    {% endif %}
  {% endif %}
  {% if post.content %}
    <p>{{ post.content }}</p><br>
  {% endif %}

  {% if post.media_filename %}
    {% set media_files = post.media_filename.split('||') %}
    {% if media_files|length > 1 %}
      <div class="media-slider">
        <div class="slider-wrapper">
          {% for media in media_files %}
            <div class="slide">
              {% if media.endswith(('.png', '.jpg', '.jpeg', '.gif')) %}
                <img src="{{ url_for('static', filename='uploads/' ~ media) }}" alt="Post image">
              {% elif media.endswith(('.mp4', '.mov')) %}

{% elif media.endswith(('.mp4', '.mov')) %}
<div class="media-wrapper" style="position: relative; text-align: center;">
  <video autoplay muted playsinline loop style="cursor:pointer; width: 100%; display: block;">
    <source src="{{ url_for('static', filename='uploads/' ~ media) }}">
  </video>
  <button class="volume-toggle" onclick="toggleGlobalAudio(this)" style="
    position: absolute;
    bottom: 10px;
    left: 10px;
    background: rgba(0, 0, 0, 0.7);
    border: none;
    color: #fff;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
  ">
    <i class="fas fa-volume-mute"></i>
  </button>
</div>








              {% elif media.endswith(('.mp3', '.wav', '.ogg')) %}
{% elif media.endswith(('.mp3', '.wav', '.ogg')) %}
<div class="media-wrapper" style="text-align: center; position: relative;">
  <div class="audio-visualization" style="width: 100%; position: relative;" onclick="handleAudioClick(this)">
    <audio autoplay muted loop style="width: 100%; display: block; min-height: 50px;" ontimeupdate="updateAudioSlider(this)">
      <source src="{{ url_for('static', filename='uploads/' ~ media) }}">
    </audio>
    <!-- Modern styled slider for progress and seeking -->
    <input type="range" class="audio-slider" value="0" min="0" max="100" onchange="seekAudio(this)" />
  </div>
  <button class="volume-toggle" onclick="toggleGlobalAudio(this)" style="
    position: relative;
    left: 0;
    margin-top: 5px;
    width: 40px;
    height: 40px;
    background: rgba(0, 0, 0, 0.7);
    border: none;
    color: #fff;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
  ">
    <i class="fas fa-volume-mute"></i>
  </button>
</div>












              {% endif %}
            </div>
          {% endfor %}
        </div>
        <button class="slider-btn prev">‹</button>
        <button class="slider-btn next">›</button>
        <div class="slider-dots"></div>
      </div>
    {% else %}
      <div class="card-media">
        {% for media in media_files %}
          {% if media.endswith(('.png', '.jpg', '.jpeg', '.gif')) %}
            <img src="{{ url_for('static', filename='uploads/' ~ media) }}" alt="Post image">
          {% elif media.endswith(('.mp4', '.mov')) %}
<div class="media-wrapper" style="position: relative; text-align: center;">
  <video autoplay muted playsinline loop style="cursor:pointer; width: 100%; display: block;">
    <source src="{{ url_for('static', filename='uploads/' ~ media) }}">
  </video>
  <button class="volume-toggle" onclick="toggleGlobalAudio(this)" style="
    position: absolute;
    bottom: 10px;
    left: 10px;
    background: rgba(0, 0, 0, 0.7);
    border: none;
    color: #fff;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
  ">
    <i class="fas fa-volume-mute"></i>
  </button>
</div>







          {% elif media.endswith(('.mp3', '.wav', '.ogg')) %}
<div class="media-wrapper" style="text-align: center; position: relative;">
  <div class="audio-visualization" style="width: 100%; position: relative;" onclick="handleAudioClick(this)">
    <audio autoplay muted loop style="width: 100%; display: block; min-height: 50px;" ontimeupdate="updateAudioSlider(this)">
      <source src="{{ url_for('static', filename='uploads/' ~ media) }}">
    </audio>
    <!-- Modern styled slider for progress and seeking -->
    <input type="range" class="audio-slider" value="0" min="0" max="100" onchange="seekAudio(this)" />
  </div>
  <button class="volume-toggle" onclick="toggleGlobalAudio(this)" style="
    position: relative;
    left: 0;
    margin-top: 5px;
    width: 40px;
    height: 40px;
    background: rgba(0, 0, 0, 0.7);
    border: none;
    color: #fff;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
  ">
    <i class="fas fa-volume-mute"></i>
  </button>
</div>








          {% endif %}
        {% endfor %}
      </div>
    {% endif %}
  {% endif %}

  <!-- Card Caption -->
  <div class="card-caption">
    {% if post.like_count_visible %}
      <span class="likes-count">{{ post.liked_by.count() }} likes</span>
    {% endif %}
  </div>

  <!-- Card Actions -->
  <div class="card-actions">
    {% if current_user in post.liked_by %}
      <a class="btn action-btn like-btn liked" href="{{ url_for('unlike', post_id=post.id) }}">
        <i class="fas fa-heart"></i>
      </a>
    {% else %}
      <a class="btn action-btn like-btn" href="{{ url_for('like', post_id=post.id) }}">
        <i class="far fa-heart"></i>
      </a>
    {% endif %}
    <a class="btn action-btn" href="{{ url_for('post_detail', post_id=post.id) }}">
      <i class="far fa-comment"></i>
    </a>
    <a class="btn action-btn" href="{{ url_for('repost', post_id=post.id) }}">
      <i class="fas fa-retweet"></i>
    </a>
  </div>

  <!-- Card Footer -->
  <div class="card-footer">
    <span class="post-date">{{ post.timestamp.strftime("%Y-%m-%d %H:%M") }}</span>
    {% if post.parent and post.is_repost %}
      <span class="repost-info">
        Original post by <a href="{{ url_for('profile', username=post.parent.author.username) }}">{{ post.parent.author.username }}</a>
      </span>
    {% endif %}
  </div>
</div>
"""




index_template = """
{% extends "base.html" %}
{% block content %}
<h2>Home Feed (All Posts)</h2><br>
<div id="postsContainer">
  {% for post in posts %}
    {% if not post.archived %}
    """ + post_card + """
    {% endif %}
    {% if loop.index % 5 == 0 %}
      <!-- Google AdSense Code Block -->
      <div class="card ad-card" style="margin-bottom: 20px; padding: 20px; text-align: center;">
        <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-1215372531548353"
             crossorigin="anonymous"></script>
        <ins class="adsbygoogle"
             style="display:block"
             data-ad-format="fluid"
             data-ad-layout-key="-6t+ed+2i-1n-4w"
             data-ad-client="ca-pub-1215372531548353"
             data-ad-slot="5880389354"></ins>
        <script>
             (adsbygoogle = window.adsbygoogle || []).push({});
        </script>
      </div>
    {% endif %}
  {% endfor %}
</div>
{% endblock %}
"""

foryou_template = """
{% extends "base.html" %}
{% block content %}
<h2>For You Feed</h2>
<div id="postsContainer">
  {% for post in posts %}
    {% if not post.archived %}
    """ + post_card + """
    {% endif %}
    {% if loop.index % 5 == 0 %}
      <!-- Google AdSense Code Block -->
      <div class="card ad-card" style="margin-bottom: 20px; padding: 20px; text-align: center;">
        <!-- Replace the code below with your actual Google AdSense ad unit code -->
        <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js"></script>
        <!-- Responsive Ad -->
        <ins class="adsbygoogle"
             style="display:block"
             data-ad-client="ca-pub-1215372531548353"
             data-ad-slot="5880389354"
             data-ad-format="auto"
             data-full-width-responsive="true"></ins>
        <script>
             (adsbygoogle = window.adsbygoogle || []).push({});
        </script>
      </div>
    {% endif %}
  {% endfor %}
</div>
{% endblock %}
"""

login_template = """
{% extends "base.html" %}
{% block content %}
<h2>Login</h2>
<form method="POST">
  <input type="text" name="username" placeholder="Username" required>
  <input type="password" name="password" placeholder="Password" required>
  <input type="submit" value="Login">
</form>
<p>Don't have an account? <a href="{{ url_for('register') }}">Register here</a>.</p>
{% endblock %}
"""

register_template = """
{% extends "base.html" %}
{% block content %}
<h2>Register</h2>
<form method="POST">
  <input type="text" name="username" placeholder="Username" required>
  <input type="email" name="email" placeholder="Email" required>
  <input type="password" name="password" placeholder="Password" required>
  <input type="submit" value="Register">
</form>
<p>Already have an account? <a href="{{ url_for('login') }}">Login here</a>.</p>
{% endblock %}
"""

settings_template = """

{% extends "base.html" %}
{% block content %}
<div class="settings-container" style="max-width: 935px; margin: 80px auto; padding: 0 20px;">
  <!-- Header -->
  <div class="settings-header" style="padding: 20px 0; border-bottom: 1px solid #dbdbdb; text-align: center;">
    <h2 style="font-weight: 300; font-size: 1.8rem;">Settings</h2>
    <div style="margin-top: 10px;">
      <a href="{{ url_for('profile', username=current_user.username) }}" class="btn" style="font-size: 0.9rem; color: #3897f0; text-decoration: none;">Back to Profile</a>
    </div>
  </div>

  <!-- Account Settings Form (Full Width) -->
  <div class="settings-form" style="margin-top: 30px; width: 100%;">
    <form method="POST" enctype="multipart/form-data" class="fullwidth-form" style="background: #fff; padding: 20px; border: 1px solid #dbdbdb; border-radius: 4px; width: 100%;">
      <div class="form-group" style="margin-bottom: 20px;">
        <label style="font-weight: bold; display: block; margin-bottom: 8px;">Account Privacy</label>
        <label style="font-size: 0.9rem;">
          <input type="checkbox" name="is_private" value="true" {% if user.is_private %}checked{% endif %}>
          Private Account
        </label>
      </div>
      <div class="form-group" style="margin-bottom: 20px;">
        <label for="profile_pic" style="font-weight: bold; display: block; margin-bottom: 8px;">Profile Picture</label>
        <input type="file" name="profile_pic" id="profile_pic" style="padding: 5px; width: 100%;">
      </div>
      <!-- New Bio Field -->
      <div class="form-group" style="margin-bottom: 20px;">
        <label for="bio" style="font-weight: bold; display: block; margin-bottom: 8px;">Bio</label>
        <textarea name="bio" id="bio" style="width: 100%; padding: 8px; border: 1px solid #dbdbdb; border-radius: 4px;" rows="3">{{ user.bio }}</textarea>
      </div>

      <!-- Inside your settings form, add this snippet -->
      <div class="form-group" style="margin-bottom: 20px;">
        <label for="dm_keypass" style="font-weight: bold; display: block; margin-bottom: 8px;">DM Keypass (for hidden chats)</label>
        <input type="text" name="dm_keypass" id="dm_keypass" placeholder="Set or update your DM keypass" value="{{ user.dm_keypass or '' }}" style="width:100%; padding:8px; border:1px solid #dbdbdb; border-radius:4px;">
      </div>
      
      <div class="form-group">
        <input type="submit" value="Save Settings" style="padding: 8px 16px; background: #3897f0; border: none; color: #fff; border-radius: 4px; cursor: pointer; width: 100%;">
      </div>
    </form>
  </div>

  <hr style="margin:30px 0;">

  <!-- Media Tabs (Buttons take full width) -->
  <div class="settings-tabs" style="text-align: center; margin-bottom: 20px;">
    <h3 style="font-weight: 300; margin-bottom: 20px;">Media</h3>
    <button id="btn-archived" class="btn" style="display: block; width: 100%; margin-bottom: 10px; padding: 12px; border: 1px solid #dbdbdb; border-radius: 4px; background: #fff; cursor: pointer;">Archived Posts</button>
    <button id="btn-liked" class="btn" style="display: block; width: 100%; margin-bottom: 10px; padding: 12px; border: 1px solid #dbdbdb; border-radius: 4px; background: #fff; cursor: pointer;">Your Likes</button>
    <button id="btn-deleted" class="btn" style="display: block; width: 100%; padding: 12px; border: 1px solid #dbdbdb; border-radius: 4px; background: #fff; cursor: pointer;">Recently Deleted</button>
  </div>
  
  <!-- Archived Posts Modal -->
  <div id="modal-archived" class="modal">
    <div class="modal-content">
      <span class="close" id="close-archived">&times;</span>
      <h3 style="font-weight: 300; margin-bottom: 20px;">Archived Posts</h3>
      {% if archived_posts %}
        <div class="profile-grid">
          {% for post in archived_posts %}
            <a href="{{ url_for('post_detail', post_id=post.id) }}" class="grid-item" style="position: relative;">
              {% if post.media_filename %}
                {% set media_files = post.media_filename.split('||') %}
                {% set first_media = media_files[0] %}
                {% if first_media.endswith(('.png', '.jpg', '.jpeg', '.gif')) %}
                  <img src="{{ url_for('static', filename='uploads/' ~ first_media) }}" alt="Post image">
                  {% if media_files|length > 1 %}
                    <div class="multiple-overlay"><i class="fas fa-clone"></i></div>
                  {% endif %}
                {% elif first_media.endswith(('.mp4', '.mov')) and post.video_thumbnail %}
                  <div class="video-thumbnail-container">
                    <img src="{{ url_for('static', filename='uploads/' ~ post.video_thumbnail) }}" alt="Video thumbnail">
                    <div class="video-play-icon">▷</div>
                    {% if media_files|length > 1 %}
                      <div class="multiple-overlay"><i class="fas fa-clone"></i></div>
                    {% endif %}
                  </div>
                {% elif first_media.endswith(('.mp3', '.wav', '.ogg')) %}
                  <div class="audio-icon-container" style="display: flex; align-items: center; justify-content: center; height:100%; width:100%; background:#f0f0f0;">
                    <i class="fas fa-music" style="font-size:50px; color:#888;"></i>
                  </div>
                  {% if media_files|length > 1 %}
                    <div class="multiple-overlay"><i class="fas fa-clone"></i></div>
                  {% endif %}
                {% else %}
                  <div class="text-post">
                    <p>{{ post.content }}</p>
                  </div>
                {% endif %}
              {% else %}
                <div class="text-post">
                  <p>{{ post.content }}</p>
                </div>
              {% endif %}
            </a>
          {% endfor %}
        </div>
      {% else %}
        <p>No archived posts.</p>
      {% endif %}
    </div>
  </div>

  <!-- Your Likes Modal -->
  <div id="modal-liked" class="modal">
    <div class="modal-content">
      <span class="close" id="close-liked">&times;</span>
      <h3 style="font-weight: 300; margin-bottom: 20px;">Your Likes</h3>
      {% if liked_posts %}
        <div class="profile-grid">
          {% for post in liked_posts %}
            <a href="{{ url_for('post_detail', post_id=post.id) }}" class="grid-item" style="position: relative;">
              {% if post.media_filename %}
                {% set media_files = post.media_filename.split('||') %}
                {% set first_media = media_files[0] %}
                {% if first_media.endswith(('.png', '.jpg', '.jpeg', '.gif')) %}
                  <img src="{{ url_for('static', filename='uploads/' ~ first_media) }}" alt="Post image">
                  {% if media_files|length > 1 %}
                    <div class="multiple-overlay"><i class="fas fa-clone"></i></div>
                  {% endif %}
                {% elif first_media.endswith(('.mp4', '.mov')) and post.video_thumbnail %}
                  <div class="video-thumbnail-container">
                    <img src="{{ url_for('static', filename='uploads/' ~ post.video_thumbnail) }}" alt="Video thumbnail">
                    <div class="video-play-icon">▷</div>
                    {% if media_files|length > 1 %}
                      <div class="multiple-overlay"><i class="fas fa-clone"></i></div>
                    {% endif %}
                  </div>
                {% elif first_media.endswith(('.mp3', '.wav', '.ogg')) %}
                  <div class="audio-icon-container" style="display: flex; align-items: center; justify-content: center; height:100%; width:100%; background:#f0f0f0;">
                    <i class="fas fa-music" style="font-size:50px; color:#888;"></i>
                  </div>
                  {% if media_files|length > 1 %}
                    <div class="multiple-overlay"><i class="fas fa-clone"></i></div>
                  {% endif %}
                {% else %}
                  <div class="text-post">
                    <p>{{ post.content }}</p>
                  </div>
                {% endif %}
              {% else %}
                <div class="text-post">
                  <p>{{ post.content }}</p>
                </div>
              {% endif %}
            </a>
          {% endfor %}
        </div>
      {% else %}
        <p>You haven't liked any posts.</p>
      {% endif %}
    </div>
  </div>
  
  <!-- Recently Deleted Modal -->
  <div id="modal-deleted" class="modal">
    <div class="modal-content">
      <span class="close" id="close-deleted">&times;</span>
      <h3 style="font-weight: 300; margin-bottom: 20px;">Recently Deleted</h3>
      {% if recently_deleted %}
        <div class="profile-grid">
          {% for post in recently_deleted %}
            <a href="{{ url_for('post_detail', post_id=post.id) }}" class="grid-item" style="position: relative;">
              {% if post.media_filename %}
                {% set media_files = post.media_filename.split('||') %}
                {% set first_media = media_files[0] %}
                {% if first_media.endswith(('.png', '.jpg', '.jpeg', '.gif')) %}
                  <img src="{{ url_for('static', filename='uploads/' ~ first_media) }}" alt="Post image">
                  {% if media_files|length > 1 %}
                    <div class="multiple-overlay"><i class="fas fa-clone"></i></div>
                  {% endif %}
                {% elif first_media.endswith(('.mp4', '.mov')) and post.video_thumbnail %}
                  <div class="video-thumbnail-container">
                    <img src="{{ url_for('static', filename='uploads/' ~ post.video_thumbnail) }}" alt="Video thumbnail">
                    <div class="video-play-icon">▷</div>
                    {% if media_files|length > 1 %}
                      <div class="multiple-overlay"><i class="fas fa-clone"></i></div>
                    {% endif %}
                  </div>
                {% elif first_media.endswith(('.mp3', '.wav', '.ogg')) %}
                  <div class="audio-icon-container" style="display: flex; align-items: center; justify-content: center; height:100%; width:100%; background:#f0f0f0;">
                    <i class="fas fa-music" style="font-size:50px; color:#888;"></i>
                  </div>
                  {% if media_files|length > 1 %}
                    <div class="multiple-overlay"><i class="fas fa-clone"></i></div>
                  {% endif %}
                {% else %}
                  <div class="text-post">
                    <p>{{ post.content }}</p>
                  </div>
                {% endif %}
              {% else %}
                <div class="text-post">
                  <p>{{ post.content }}</p>
                </div>
              {% endif %}
            </a>
          {% endfor %}
        </div>
      {% else %}
        <p>No recently deleted posts.</p>
      {% endif %}
    </div>
  </div>
</div>

<!-- Modal Popup JavaScript -->
<script>
  var modalArchived = document.getElementById("modal-archived");
  var modalLiked = document.getElementById("modal-liked");
  var modalDeleted = document.getElementById("modal-deleted");

  var btnArchived = document.getElementById("btn-archived");
  var btnLiked = document.getElementById("btn-liked");
  var btnDeleted = document.getElementById("btn-deleted");

  var closeArchived = document.getElementById("close-archived");
  var closeLiked = document.getElementById("close-liked");
  var closeDeleted = document.getElementById("close-deleted");

  btnArchived.onclick = function() {
    modalArchived.style.display = "block";
  }
  btnLiked.onclick = function() {
    modalLiked.style.display = "block";
  }
  btnDeleted.onclick = function() {
    modalDeleted.style.display = "block";
  }
  closeArchived.onclick = function() {
    modalArchived.style.display = "none";
  }
  closeLiked.onclick = function() {
    modalLiked.style.display = "none";
  }
  closeDeleted.onclick = function() {
    modalDeleted.style.display = "none";
  }
  window.onclick = function(event) {
    if (event.target == modalArchived) {
      modalArchived.style.display = "none";
    }
    if (event.target == modalLiked) {
      modalLiked.style.display = "none";
    }
    if (event.target == modalDeleted) {
      modalDeleted.style.display = "none";
    }
  }
</script>

<hr style="margin:30px 0;">
{% endblock %}


"""

edit_post_template = """
{% extends "base.html" %}
{% block content %}
<h2>Edit Post</h2>
<form method="POST">
  <textarea name="content" rows="4">{{ post.content }}</textarea>
  <input type="submit" value="Update">
</form>
{% endblock %}
"""

# New template: Post Detail Page (shows post and its comments recursively)
post_detail_template = """
{% extends "base.html" %}
{% block content %}
<div class="post-detail" style="position: relative;">
  <div class="card enhanced-post-card">
    <!-- Card Header -->
    <div class="card-header">
      <div class="author-info">
        {% if post.author.profile_pic %}
          <img class="card-profile-pic" src="{{ url_for('static', filename='uploads/' ~ post.author.profile_pic) }}" alt="{{ post.author.username }}'s profile picture">
        {% else %}
          <img class="card-profile-pic" src="{{ url_for('static', filename='uploads/default_profile.png') }}" alt="{{ post.author.username }}'s profile picture">
        {% endif %}
        <a href="{{ url_for('profile', username=post.author.username) }}" class="author-username">
          {{ post.author.username }}
        </a>
      </div>
      {% if current_user.id == post.author.id %}
      <div class="post-options">
        <div class="dropdown">
          <button class="dropbtn" onclick="toggleDropdown(this)">⋮</button>
          <div class="dropdown-content">
            {% if not post.deleted %}
              <a href="{{ url_for('delete_post', post_id=post.id) }}">Delete</a>
              <a href="{{ url_for('pin_post', post_id=post.id) }}">
                {{ 'Unpin' if post.pinned else 'Pin' }}
              </a>
              <a href="{{ url_for('edit_post', post_id=post.id) }}">Edit</a>
              <a href="{{ url_for('toggle_comments', post_id=post.id) }}">
                {{ 'Turn On Comments' if not post.comments_enabled else 'Turn Off Comments' }}
              </a>
              <a href="{{ url_for('toggle_like_visibility', post_id=post.id) }}">
                {{ 'Show Like Count' if not post.like_count_visible else 'Hide Like Count' }}
              </a>
              <a href="{{ url_for('archive_post', post_id=post.id) }}">
                {{ 'Unarchive' if post.archived else 'Archive' }}
              </a>
            {% else %}
              <a href="{{ url_for('restore_post', post_id=post.id) }}">Restore</a>
              <a href="{{ url_for('permanently_delete_post', post_id=post.id) }}">Permanently Delete</a>
            {% endif %}
          </div>
        </div>
      </div>
      {% endif %}
    </div>

    {% if post.is_repost %}
      {% if post.parent %}
        <p><strong>{{ post.author.username }}</strong> reposted <strong>{{ post.parent.author.username }}</strong>'s post:</p>
      {% else %}
        <p><strong>{{ post.author.username }}</strong> reposted a comment:</p>
      {% endif %}
    {% endif %}
    
    <br>
    
    <!-- Card Media and Content -->
    {% if post.content %}
      <p>{{ post.content }}</p><br>
    {% endif %}
    {% if post.media_filename %}
      {% set media_files = post.media_filename.split('||') %}
      {% if media_files|length > 1 %}
        <div class="media-slider">
          <div class="slider-wrapper">
            {% for media in media_files %}
              <div class="slide">
                {% if media.endswith(('.png', '.jpg', '.jpeg', '.gif')) %}
                  <img src="{{ url_for('static', filename='uploads/' ~ media) }}" alt="Post image">
                {% elif media.endswith(('.mp4', '.mov')) %}
                  <div class="media-wrapper" style="position: relative; text-align: center;">
                    <video autoplay muted playsinline loop preload="auto" style="cursor:pointer; width: 100%; display: block;">
                      <source src="{{ url_for('static', filename='uploads/' ~ media) }}">
                    </video>
                    <button class="volume-toggle" onclick="toggleGlobalAudio(this)" style="position: absolute; bottom: 10px; left: 10px; background: rgba(0,0,0,0.7); border: none; color: #fff; width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center;">
                      <i class="fas fa-volume-mute"></i>
                    </button>
                  </div>
                {% elif media.endswith(('.mp3', '.wav', '.ogg')) %}
                  <div class="media-wrapper" style="text-align: center; position: relative;">
                    <div class="audio-visualization" style="width: 100%; position: relative;" onclick="handleAudioClick(this)">
                      <audio autoplay muted loop preload="auto" style="width: 100%; display: block; min-height: 50px;" ontimeupdate="updateAudioSlider(this)">
                        <source src="{{ url_for('static', filename='uploads/' ~ media) }}">
                      </audio>
                      <input type="range" class="audio-slider" value="0" min="0" max="100" onchange="seekAudio(this)" />
                    </div>
                    <button class="volume-toggle" onclick="toggleGlobalAudio(this)" style="position: relative; left: 0; margin-top: 5px; width: 40px; height: 40px; background: rgba(0,0,0,0.7); border: none; color: #fff; border-radius: 50%; display: flex; align-items: center; justify-content: center;">
                      <i class="fas fa-volume-mute"></i>
                    </button>
                  </div>
                {% endif %}
              </div>
            {% endfor %}
          </div>
          <button class="slider-btn prev">‹</button>
          <button class="slider-btn next">›</button>
          <div class="slider-dots"></div>
        </div>
      {% else %}
        <div class="card-media">
          {% for media in media_files %}
            {% if media.endswith(('.png', '.jpg', '.jpeg', '.gif')) %}
              <img src="{{ url_for('static', filename='uploads/' ~ media) }}" alt="Post image">
            {% elif media.endswith(('.mp4', '.mov')) %}
              <div class="media-wrapper" style="position: relative; text-align: center;">
                <video autoplay muted playsinline loop preload="auto" style="cursor:pointer; width: 100%; display: block;">
                  <source src="{{ url_for('static', filename='uploads/' ~ media) }}">
                </video>
                <button class="volume-toggle" onclick="toggleGlobalAudio(this)" style="position: absolute; bottom: 10px; left: 10px; background: rgba(0,0,0,0.7); border: none; color: #fff; width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center;">
                  <i class="fas fa-volume-mute"></i>
                </button>
              </div>
            {% elif media.endswith(('.mp3', '.wav', '.ogg')) %}
              <div class="media-wrapper" style="text-align: center; position: relative;">
                <div class="audio-visualization" style="width: 100%; position: relative;" onclick="handleAudioClick(this)">
                  <audio autoplay muted loop preload="auto" style="width: 100%; display: block; min-height: 50px;" ontimeupdate="updateAudioSlider(this)">
                    <source src="{{ url_for('static', filename='uploads/' ~ media) }}">
                  </audio>
                  <input type="range" class="audio-slider" value="0" min="0" max="100" onchange="seekAudio(this)" />
                </div>
                <button class="volume-toggle" onclick="toggleGlobalAudio(this)" style="position: relative; left: 0; margin-top: 5px; width: 40px; height: 40px; background: rgba(0,0,0,0.7); border: none; color: #fff; border-radius: 50%; display: flex; align-items: center; justify-content: center;">
                  <i class="fas fa-volume-mute"></i>
                </button>
              </div>
            {% endif %}
          {% endfor %}
        </div>
      {% endif %}
    {% endif %}
    
    <!-- Card Actions -->
    <div class="card-actions">
      {% if current_user in post.liked_by %}
        <a class="btn action-btn like-btn liked" href="{{ url_for('unlike', post_id=post.id) }}">
          <i class="fas fa-heart"></i>
        </a>
      {% else %}
        <a class="btn action-btn like-btn" href="{{ url_for('like', post_id=post.id) }}">
          <i class="far fa-heart"></i>
        </a>
      {% endif %}
      {% if post.comments_enabled %}
        <a class="btn action-btn" href="{{ url_for('post_detail', post_id=post.id) }}#comment-form">
          <i class="far fa-comment"></i>
        </a>
      {% else %}
        <span class="btn action-btn disabled-comment">
          <i class="fas fa-comment-slash"></i>
        </span>
      {% endif %}
      <a class="btn action-btn" href="{{ url_for('repost', post_id=post.id) }}">
        <i class="fas fa-retweet"></i>
      </a>
    </div>
    
    <!-- Card Caption -->
    <div class="card-caption">
      {% if post.like_count_visible %}
        <span class="likes-count">{{ post.liked_by.count() }} likes</span>
      {% endif %}
    </div>
    
    <!-- Card Footer -->
    <div class="card-footer">
      <span class="post-date">{{ post.timestamp.strftime("%Y-%m-%d %H:%M") }}</span>
    </div>
  </div>
  
  <!-- Comments Section -->
  {% if post.comments_enabled %}
  <div class="comments-section" style="margin:20px auto; font-family: sans-serif; padding-bottom: 80px;">
    <!-- Comments List -->
    <div class="comments-list">
      {% for comment in post.comments if not comment.parent %}
        <div class="comment-item" style="display: flex; align-items: flex-start; padding: 10px 0;">
          <div class="comment-profile" style="margin-right: 10px;">
            {% if comment.author.profile_pic %}
              <img src="{{ url_for('static', filename='uploads/' ~ comment.author.profile_pic) }}" alt="{{ comment.author.username }}'s profile picture" style="width:32px; height:32px; border-radius:50%;">
            {% else %}
              <img src="{{ url_for('static', filename='uploads/default_profile.png') }}" alt="{{ comment.author.username }}'s profile picture" style="width:32px; height:32px; border-radius:50%;">
            {% endif %}
          </div>
          <div class="comment-content" style="flex:1;">
            <div>
              <span style="font-weight: bold; margin-right: 5px; font-size:14px;">{{ comment.author.username }}</span>
              <span style="font-size:14px;">{{ comment.content }}</span>
            </div>
            {% if comment.media_filename %}
              <div class="comment-media" style="margin-top:5px;">
                {% if comment.media_filename.endswith(('.png', '.jpg', '.jpeg', '.gif')) %}
                  <img src="{{ url_for('static', filename='uploads/' ~ comment.media_filename) }}" style="max-width:150px; border-radius:5px;">
                {% elif comment.media_filename.endswith(('.mp4', '.mov')) %}
                  <div class="media-wrapper" style="position: relative; text-align: center;">
                    <video autoplay muted playsinline loop preload="auto" style="cursor:pointer; max-width:150px; border-radius:5px;">
                      <source src="{{ url_for('static', filename='uploads/' ~ comment.media_filename) }}">
                    </video>
                    <button class="volume-toggle" onclick="toggleGlobalAudio(this)" style="position: absolute; bottom: 5px; left: 5px; background: rgba(0,0,0,0.7); border: none; color: #fff; width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center;">
                      <i class="fas fa-volume-mute"></i>
                    </button>
                  </div>
                {% elif comment.media_filename.endswith(('.mp3', '.wav', '.ogg')) %}
                  <div class="media-wrapper" style="text-align: center; position: relative;">
                    <div class="audio-visualization" style="width: 100%; position: relative;" onclick="handleAudioClick(this)">
                      <audio autoplay muted loop preload="auto" style="width: 100%; display: block; min-height: 50px;" ontimeupdate="updateAudioSlider(this)">
                        <source src="{{ url_for('static', filename='uploads/' ~ comment.media_filename) }}">
                      </audio>
                      <input type="range" class="audio-slider" value="0" min="0" max="100" onchange="seekAudio(this)" />
                    </div>
                    <button class="volume-toggle" onclick="toggleGlobalAudio(this)" style="position: relative; left: 0; margin-top: 5px; width: 30px; height: 30px; background: rgba(0,0,0,0.7); border: none; color: #fff; border-radius: 50%; display: flex; align-items: center; justify-content: center;">
                      <i class="fas fa-volume-mute"></i>
                    </button>
                  </div>
                {% endif %}
              </div>
            {% endif %}
            <div class="comment-meta" style="font-size:12px; color:#8e8e8e; margin-top:3px;">
              {{ comment.timestamp.strftime("%Y-%m-%d %H:%M") }}
            </div>
            <!-- Comment Actions for Replying and Reposting -->
            <div class="comment-actions" style="margin-top:5px;">
              <a class="btn reply-btn" href="{{ url_for('post_detail', post_id=post.id) }}?parent={{ comment.id }}" style="margin-right:10px; font-size:0.9rem; color:#3897f0; text-decoration:none;">
                <i class="fas fa-reply"></i> Reply
              </a>
              <a class="btn reply-btn repost-comment-btn" href="{{ url_for('repost_comment', comment_id=comment.id) }}" style="font-size:0.9rem; color:#3897f0; text-decoration:none;">
                <i class="fas fa-retweet"></i> Repost
              </a>
            </div>
          </div>
        </div>
        {% for child in comment.children %}
          <div class="comment-item reply" style="display: flex; align-items: flex-start; padding: 8px 0; padding-left:40px;">
            <div class="comment-profile" style="margin-right: 10px;">
              {% if child.author.profile_pic %}
                <img src="{{ url_for('static', filename='uploads/' ~ child.author.profile_pic) }}" alt="{{ child.author.username }}'s profile picture" style="width:28px; height:28px; border-radius:50%;">
              {% else %}
                <img src="{{ url_for('static', filename='uploads/default_profile.png') }}" alt="{{ child.author.username }}'s profile picture" style="width:28px; height:28px; border-radius:50%;">
              {% endif %}
            </div>
            <div class="comment-content" style="flex:1;">
              <div>
                <span style="font-weight: bold; margin-right: 5px; font-size:13px;">{{ child.author.username }}</span>
                <span style="font-size:13px;">{{ child.content }}</span>
              </div>
              {% if child.media_filename %}
                <div class="comment-media" style="margin-top:5px;">
                  {% if child.media_filename.endswith(('.png', '.jpg', '.jpeg', '.gif')) %}
                    <img src="{{ url_for('static', filename='uploads/' ~ child.media_filename) }}" style="max-width:140px; border-radius:5px;">
                  {% elif child.media_filename.endswith(('.mp4', '.mov')) %}
                    <div class="media-wrapper" style="position: relative; text-align: center;">
                      <video autoplay muted playsinline loop preload="auto" style="cursor:pointer; max-width:140px; border-radius:5px;">
                        <source src="{{ url_for('static', filename='uploads/' ~ child.media_filename) }}">
                      </video>
                      <button class="volume-toggle" onclick="toggleGlobalAudio(this)" style="position: absolute; bottom: 5px; left: 5px; background: rgba(0,0,0,0.7); border: none; color: #fff; width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center;">
                        <i class="fas fa-volume-mute"></i>
                      </button>
                    </div>
                  {% elif child.media_filename.endswith(('.mp3', '.wav', '.ogg')) %}
                    <div class="media-wrapper" style="text-align: center; position: relative;">
                      <div class="audio-visualization" style="width: 100%; position: relative;" onclick="handleAudioClick(this)">
                        <audio autoplay muted loop preload="auto" style="width: 100%; display: block; min-height: 50px;" ontimeupdate="updateAudioSlider(this)">
                          <source src="{{ url_for('static', filename='uploads/' ~ child.media_filename) }}">
                        </audio>
                        <input type="range" class="audio-slider" value="0" min="0" max="100" onchange="seekAudio(this)" />
                      </div>
                      <button class="volume-toggle" onclick="toggleGlobalAudio(this)" style="position: relative; left: 0; margin-top: 5px; width: 30px; height: 30px; background: rgba(0,0,0,0.7); border: none; color: #fff; border-radius: 50%; display: flex; align-items: center; justify-content: center;">
                        <i class="fas fa-volume-mute"></i>
                      </button>
                    </div>
                  {% endif %}
                </div>
              {% endif %}
              <div class="comment-meta" style="font-size:11px; color:#8e8e8e; margin-top:3px;">
                {{ child.timestamp.strftime("%Y-%m-%d %H:%M") }}
              </div>
              <!-- Comment Actions for Replies -->
              <div class="comment-actions" style="margin-top:5px;">
                <a class="btn reply-btn" href="{{ url_for('post_detail', post_id=post.id) }}?parent={{ child.id }}" style="margin-right:10px; font-size:0.8rem; color:#3897f0; text-decoration:none;">
                  <i class="fas fa-reply"></i> Reply
                </a>
                <a class="btn reply-btn repost-comment-btn" href="{{ url_for('repost_comment', comment_id=child.id) }}" style="font-size:0.8rem; color:#3897f0; text-decoration:none;">
                  <i class="fas fa-retweet"></i> Repost
                </a>
              </div>
            </div>
          </div>
        {% endfor %}
      {% endfor %}
    </div>
  
    <!-- Floating Comment Form -->
    <div class="floating-comment-form" id="comment-form" style="position: sticky; bottom: 0; background: #fff; padding: 10px; border-top: 1px solid #efefef; z-index: 10;">
      {% if parent_comment %}
      <div class="replying-to" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: #f0f0f0; border: 1px solid #ccc; border-radius: 20px; margin-bottom: 8px; font-size: 0.9rem;">
        <span>Replying to <strong>{{ parent_comment.author.username }}</strong></span>
        <a href="{{ url_for('post_detail', post_id=post.id) }}" style="margin-left: 12px; color: #3897f0; text-decoration: none; font-weight: bold;">×</a>
      </div>
      {% endif %}
      <form method="POST" enctype="multipart/form-data" style="width:100%; display: flex; align-items: center;">
        <input type="text" name="content" placeholder="Add a comment..." required style="flex:1; border:none; outline:none; padding:8px; font-size:14px;">
        <!-- Preview container for selected media -->
        <div id="comment-media-preview" style="width:40px; height:40px; margin-right:8px; overflow:hidden; border-radius:4px;"></div>
        <label for="comment-media" style="cursor:pointer; margin:0 8px;">
          <i class="fas fa-image" style="color:#3897f0; font-size:18px;"></i>
        </label>
        <input type="file" id="comment-media" name="media" accept="image/*,video/*" style="display:none;">
        {% if parent_comment_id %}
          <input type="hidden" name="parent_id" value="{{ parent_comment_id }}">
        {% endif %}
        <button type="submit" style="background:none; border:none; color:#3897f0; font-weight:bold; cursor:pointer; padding:8px; font-size:14px;">Post</button>
      </form>
    </div>
  </div>
  
  <!-- JavaScript for previewing selected media in comment form -->
  <script>
    document.getElementById('comment-media').addEventListener('change', function(e) {
      const previewContainer = document.getElementById('comment-media-preview');
      previewContainer.innerHTML = ''; // Clear previous preview
      const file = this.files[0];
      if (!file) return;
      
      const reader = new FileReader();
      reader.onload = function(event) {
        if (file.type.startsWith('image/')) {
          const img = document.createElement('img');
          img.src = event.target.result;
          img.style.width = '100%';
          img.style.height = '100%';
          img.style.objectFit = 'cover';
          previewContainer.appendChild(img);
        } else if (file.type.startsWith('video/')) {
          const video = document.createElement('video');
          video.src = event.target.result;
          video.controls = false;
          video.style.width = '100%';
          video.style.height = '100%';
          video.style.objectFit = 'cover';
          previewContainer.appendChild(video);
        }
      };
      reader.readAsDataURL(file);
    });
  </script>
{% else %}
  <p class="no-comments" style="text-align:center; padding:20px; color:#8e8e8e;">Comments are turned off for this post.</p>
{% endif %}
</div>
{% endblock %}

"""

app.jinja_loader = DictLoader({
    "base.html": base_template,
    "index.html": index_template,
    "foryou.html": foryou_template,
    "login.html": login_template,
    "register.html": register_template,
    "profile.html": """
{% extends "base.html" %}
{% block content %}
<!-- Instagram-like Profile Header -->
<div class="profile-header" style="display:flex; align-items:center; margin-bottom:20px;">
  <!-- Profile Picture -->
  <div class="profile-picture" style="flex: 0 0 150px;">
    {% if user.profile_pic %}
      <img src="{{ url_for('static', filename='uploads/' ~ user.profile_pic) }}"
           alt="{{ user.username }}'s profile picture"
           style="width:150px; height:150px; border-radius:50%; object-fit:cover; border: 1px solid #dbdbdb;">
    {% else %}
      <img src="{{ url_for('static', filename='uploads/default_profile.png') }}"
           alt="{{ user.username }}'s profile picture"
           style="width:150px; height:150px; border-radius:50%; object-fit:cover; border: 1px solid #dbdbdb;">
    {% endif %}
  </div>
  <!-- Profile Info and Stats -->
  <div class="profile-info" style="flex:1; margin-left:30px;">
    <h2 style="font-size:28px; font-weight:300;">{{ user.username }}</h2>
    <ul class="profile-stats" style="display:flex; list-style:none; padding:0; margin:10px 0;">
      <li style="margin-right:20px;"><span style="font-weight:600;">{{ posts|length }}</span> posts</li>
      <li style="margin-right:20px;"><span style="font-weight:600;">{{ user.followers.count() }}</span> followers</li>
      <li><span style="font-weight:600;">{{ user.followed.count() }}</span> following</li>
    </ul>

    {% if user.bio %}
      <p class="profile-bio" style="font-size:14px; color:#262626;">bio: {{ user.bio }}</p>
    {% endif %}
    
    <p class="profile-bio" style="font-size:14px; color:#262626;">{{ user.email }}</p>
    {% if current_user.username == user.username %}
      <a href="{{ url_for('profile_settings', username=user.username) }}" class="btn" style="margin-top:10px;">Edit Profile</a>
    {% endif %}
    {% if current_user.username != user.username %}
      {% if current_user in user.followers %}
        <a class="btn" href="{{ url_for('unfollow', username=user.username) }}" style="margin-top:10px;">Unfollow</a>
      {% else %}
        {% if pending_request %}
          <a class="btn" href="{{ url_for('cancel_request', username=user.username) }}" style="margin-top:10px;">Cancel Follow Request</a>
        {% else %}
          <a class="btn" href="{{ url_for('follow', username=user.username) }}" style="margin-top:10px;">Follow</a>
        {% endif %}
      {% endif %}
    {% endif %}
  </div>

  {% if current_user.username != user.username %}
    <a href="{{ url_for('new_dm', username=user.username) }}" class="btn" style="margin-top:10px;">Message</a>
  {% endif %}
</div>

<!-- Tab Navigation -->
<div class="profile-tabs" style="display:flex; justify-content:center; border-top:1px solid #dbdbdb; border-bottom:1px solid #dbdbdb; margin-bottom:20px;">
  <a href="{{ url_for('profile', username=user.username) }}?tab=posts" class="tab {% if request.args.get('tab', 'posts') == 'posts' %}active{% endif %}" style="flex:1; text-align:center; padding:10px; text-decoration:none; color:#262626;">
    <i class="fas fa-th"></i>
  </a>
  <a href="{{ url_for('profile', username=user.username) }}?tab=reposts" class="tab {% if request.args.get('tab') == 'reposts' %}active{% endif %}" style="flex:1; text-align:center; padding:10px; text-decoration:none; color:#262626;">
    <i class="fas fa-retweet"></i>
  </a>
  <a href="{{ url_for('profile', username=user.username) }}?tab=comments" class="tab {% if request.args.get('tab') == 'comments' %}active{% endif %}" style="flex:1; text-align:center; padding:10px; text-decoration:none; color:#262626;">
    <i class="fas fa-comment"></i>
  </a>
</div>

<!-- Tab Content -->
<div class="profile-content">
  {% set active_tab = request.args.get('tab', 'posts') %}
  {% if active_tab == 'posts' %}
    <div class="profile-grid">
      {% for post in posts if not post.archived and not post.is_repost %}
        {% if post.media_filename %}
          {% set media_files = post.media_filename.split('||') %}
          {% if media_files|length > 1 %}
            <!-- For carousel posts, show first media as thumbnail with an overlay indicator -->
            <a href="{{ url_for('post_detail', post_id=post.id) }}" class="grid-item image-post" style="position: relative;">
              {% if media_files[0].endswith(('.png', '.jpg', '.jpeg', '.gif')) %}
                <img src="{{ url_for('static', filename='uploads/' ~ media_files[0]) }}" alt="Post image">
              {% elif media_files[0].endswith(('.mp4', '.mov')) and post.video_thumbnail %}
                <div class="video-thumbnail-container">
                  <img src="{{ url_for('static', filename='uploads/' ~ post.video_thumbnail) }}" alt="Video thumbnail">
                  <div class="video-play-icon">▷</div>
                </div>
              {% elif media_files[0].endswith(('.mp3', '.wav', '.ogg')) %}
                <div class="audio-icon-container" style="display: flex; align-items: center; justify-content: center; height:100%; width:100%; background:#f0f0f0;">
                  <i class="fas fa-music" style="font-size:50px; color:#888;"></i>
                </div>
                <div class="carousel-indicator" style="position:absolute; bottom:8px; right:8px; background:rgba(0,0,0,0.5); border-radius:50%; padding:4px; padding-top:15%; padding-bottom:15%;">
                  <i class="fas fa-clone" style="color:#fff; font-size:12px;"></i>
                </div>
              {% endif %}
            </a>
          {% else %}
            {% if post.media_filename.endswith(('.png', '.jpg', '.jpeg', '.gif')) %}
              <a href="{{ url_for('post_detail', post_id=post.id) }}" class="grid-item image-post">
                <img src="{{ url_for('static', filename='uploads/' ~ post.media_filename) }}" alt="Post image">
              </a>
            {% elif post.media_filename.endswith(('.mp4', '.mov')) and post.video_thumbnail %}
              <a href="{{ url_for('post_detail', post_id=post.id) }}" class="grid-item image-post">
                <div class="video-thumbnail-container">
                  <img src="{{ url_for('static', filename='uploads/' ~ post.video_thumbnail) }}" alt="Video thumbnail">
                  <div class="video-play-icon">▷</div>
                </div>
              </a>
            {% elif post.media_filename.endswith(('.mp3', '.wav', '.ogg')) %}
              <a href="{{ url_for('post_detail', post_id=post.id) }}" class="grid-item audio-post" style="position: relative;">
                <div class="audio-icon-container" style="display: flex; align-items: center; justify-content: center; height:100%; width:100%; background:#f0f0f0; padding-top:15%; padding-bottom:15%;">
                  <i class="fas fa-music" style="font-size:50px; color:#888;"></i>
                </div>
              </a>
            {% else %}
              <a href="{{ url_for('post_detail', post_id=post.id) }}" class="grid-item text-post">
                <div class="text-content">
                  <p>{{ post.content }}</p>
                </div>
              </a>
            {% endif %}
          {% endif %}
        {% else %}
          <a href="{{ url_for('post_detail', post_id=post.id) }}" class="grid-item text-post">
            <div class="text-content">
              <p>{{ post.content }}</p>
            </div>
          </a>
        {% endif %}
      {% endfor %}
    </div>
  {% elif active_tab == 'reposts' %}
    <div class="profile-grid">
      {% for repost in reposts if not repost.archived %}
        {% if repost.media_filename and repost.media_filename.endswith(('.png', '.jpg', '.jpeg', '.gif')) %}
          <a href="{{ url_for('post_detail', post_id=repost.id) }}" class="grid-item image-post">
            <img src="{{ url_for('static', filename='uploads/' ~ repost.media_filename) }}" alt="Repost image">
          </a>


            {% elif repost.media_filename.endswith(('.mp4', '.mov')) and repost.video_thumbnail %}
              <a href="{{ url_for('post_detail', post_id=repost.id) }}" class="grid-item image-post">
                <div class="video-thumbnail-container">
                  <img src="{{ url_for('static', filename='uploads/' ~ repost.video_thumbnail) }}" alt="Video thumbnail">
                  <div class="video-play-icon">▷</div>
                </div>
              </a>

            {% elif repost.media_filename.endswith(('.mp3', '.wav', '.ogg')) %}
              <a href="{{ url_for('post_detail', post_id=repost.id) }}" class="grid-item audio-post" style="position: relative;">
                <div class="audio-icon-container" style="display: flex; align-items: center; justify-content: center; height:100%; width:100%; background:#f0f0f0; padding-top:15%; padding-bottom:15%;">
                  <i class="fas fa-music" style="font-size:50px; color:#888;"></i>
                </div>
              </a>



        {% else %}
          <a href="{{ url_for('post_detail', post_id=repost.id) }}" class="grid-item text-post">
            <div class="text-content">
              <p>{{ repost.content }}</p>
            </div>
          </a>
        {% endif %}
      {% endfor %}
    </div>
  {% elif active_tab == 'comments' %}
    <div class="comments-list">
      {% for comment in comments %}
        <div class="comment-card" style="border-bottom:1px solid #efefef; padding:10px 0;">
          <div class="comment-header" style="display:flex; align-items:center;">
            {% if comment.author.profile_pic %}
              <img class="comment-profile-pic" src="{{ url_for('static', filename='uploads/' ~ comment.author.profile_pic) }}" alt="{{ comment.author.username }}'s profile picture" style="width:40px; height:40px; border-radius:50%; margin-right:10px;">
            {% else %}
              <img class="comment-profile-pic" src="{{ url_for('static', filename='uploads/default_profile.png') }}" alt="Default profile" style="width:40px; height:40px; border-radius:50%; margin-right:10px;">
            {% endif %}
            <a href="{{ url_for('profile', username=comment.author.username) }}" style="font-weight:600; color:#262626; text-decoration:none;">
              {{ comment.author.username }}
            </a>
            <span style="margin-left:10px; color:#8e8e8e; font-size:0.9rem;">{{ comment.timestamp.strftime("%Y-%m-%d %H:%M") }}</span>
          </div>
          <div class="comment-body" style="margin-top:5px;">
            <p style="margin:0;">{{ comment.content }}</p>
            {% if comment.media_filename %}
              {% if comment.media_filename.endswith(('.png', '.jpg', '.jpeg', '.gif')) %}
                <img src="{{ url_for('static', filename='uploads/' ~ comment.media_filename) }}" style="max-width:200px; margin-top:5px;">
              {% elif comment.media_filename.endswith(('.mp4', '.mov')) %}
                <video controls style="max-width:200px; margin-top:5px;">
                  <source src="{{ url_for('static', filename='uploads/' ~ comment.media_filename) }}">
                </video>
              {% endif %}
            {% endif %}
          </div>
        </div>
      {% endfor %}
    </div>
  {% endif %}
</div>
{% endblock %}


""",
    "settings.html": settings_template,
    "new_post.html": """
{% extends "base.html" %}
{% block content %}
<div class="new-post-container" style="max-width:600px; margin: 40px auto; background: #fff; border: 1px solid #dbdbdb; border-radius: 8px; padding: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);">
  <h2 style="text-align:center; font-weight:300; margin-bottom:20px;">Create a New Post</h2>
  <form method="POST" enctype="multipart/form-data">
    <textarea name="content" placeholder="What's on your mind?" rows="4" style="width:100%; border: none; outline: none; resize: none; font-size: 1rem; padding: 10px;"></textarea>
    
    <!-- Preview container -->
    <div id="media-preview" style="margin-top:15px;"></div>
    
    <div class="new-post-actions" style="display:flex; justify-content:space-between; align-items:center; margin-top:15px;">
      <label for="media" style="cursor:pointer; display:inline-block; background:#0095f6; color:#fff; padding:10px 15px; border-radius:4px;">
        <i class="fas fa-image"></i> Add Photo/Video/Audio
      </label>
      <!-- Updated accept attribute to include audio -->
      <input type="file" name="media" id="media" accept="image/*,video/*,audio/*" multiple style="display:none;">
      <input type="submit" value="Post" style="background:#0095f6; color:#fff; border:none; padding:10px 20px; border-radius:4px; cursor:pointer;">
    </div>
  </form>
</div>

<script>
  const mediaInput = document.getElementById('media');
  const mediaPreview = document.getElementById('media-preview');

  mediaInput.addEventListener('change', function(event) {
    // Clear previous previews
    mediaPreview.innerHTML = '';
    const files = event.target.files;
    if (!files.length) return;
    
    Array.from(files).forEach(file => {
      const fileType = file.type;
      const reader = new FileReader();

      reader.addEventListener('load', function(e) {
        if (fileType.startsWith('image/')) {
          const img = document.createElement('img');
          img.src = e.target.result;
          img.style.maxWidth = '100%';
          img.style.marginTop = '15px';
          mediaPreview.appendChild(img);
        } else if (fileType.startsWith('video/')) {
          const video = document.createElement('video');
          video.src = e.target.result;
          video.controls = true;
          video.style.maxWidth = '100%';
          video.style.marginTop = '15px';
          mediaPreview.appendChild(video);
        } else if (fileType.startsWith('audio/')) {
          const audio = document.createElement('audio');
          audio.src = e.target.result;
          audio.controls = true;
          audio.style.maxWidth = '100%';
          audio.style.marginTop = '15px';
          mediaPreview.appendChild(audio);
        }
      });
      reader.readAsDataURL(file);
    });
  });
</script>
{% endblock %}

""",
    # Remove the old comment.html since we're using a unified post detail page.
    "post_detail.html": post_detail_template,
    "followers_list.html": """{% extends "base.html" %}{% block content %}<h2>Followers of {{ user.username }}</h2><ul>{% for follower in followers %}<li><a href="{{ url_for('profile', username=follower.username) }}">{{ follower.username }}</a></li>{% endfor %}</ul><a class="btn" href="{{ url_for('profile', username=user.username) }}">Back to Profile</a>{% endblock %}""",
    "following_list.html": """{% extends "base.html" %}{% block content %}<h2>{{ user.username }} is following</h2><ul>{% for u in following %}<li><a href="{{ url_for('profile', username=u.username) }}">{{ u.username }}</a></li>{% endfor %}</ul><a class="btn" href="{{ url_for('profile', username=user.username) }}">Back to Profile</a>{% endblock %}""",
    "user_posts.html": """{% extends "base.html" %}{% block content %}<h2>{{ user.username }}'s Posts</h2>{% for post in posts %}<div class="card"><div class="card-content"><p>{{ post.content }}</p></div></div>{% endfor %}<a class="btn" href="{{ url_for('profile', username=user.username) }}">Back to Profile</a>{% endblock %}""",
    "follow_requests.html": """{% extends "base.html" %}{% block content %}<h2>Follow Requests</h2>{% if requests %}<ul>{% for req in requests %}<li><a href="{{ url_for('profile', username=req.requester.username) }}">{{ req.requester.username }}</a> (<a class="btn" href="{{ url_for('accept_request', request_id=req.id) }}">Accept</a> <a class="btn" href="{{ url_for('reject_request', request_id=req.id) }}">Reject</a>)</li>{% endfor %}</ul>{% else %}<p>No follow requests.</p>{% endif %}{% endblock %}""",
    "search.html": """{% extends "base.html" %}
{% block content %}
<div class="search-container">
  <h2><i class="fas fa-search"></i> Search Users</h2>
  <!-- Search Bar -->
  <form method="GET" action="{{ url_for('search') }}" class="search-box">
    <input type="text" name="q" placeholder="Search by username" value="{{ query }}">
    <button type="submit"><i class="fas fa-search"></i></button>
  </form>

  {% if query %}
    <h3>Results for "{{ query }}":</h3>
    <ul class="search-results">
      {% for user in results %}
        <li>
          <a href="{{ url_for('profile', username=user.username) }}">
            {% if user.profile_pic %}
              <img src="{{ url_for('static', filename='uploads/' ~ user.profile_pic) }}" alt="{{ user.username }}'s profile picture">
            {% else %}
              <img src="{{ url_for('static', filename='uploads/default_profile.png') }}" alt="Default profile picture">
            {% endif %}
            <span>{{ user.username }}</span>
          </a>
        </li>
      {% endfor %}
    </ul>
  {% else %}
    <h3>Recommendations</h3>
    <div class="recommendations-grid">
      {% for rec in recommendations %}
        <div class="recommendation-item">
          <a href="{{ url_for('profile', username=rec.username) }}">
            {% if rec.profile_pic %}
              <img src="{{ url_for('static', filename='uploads/' ~ rec.profile_pic) }}" alt="{{ rec.username }}'s profile picture">
            {% else %}
              <img src="{{ url_for('static', filename='uploads/default_profile.png') }}" alt="Default profile picture">
            {% endif %}
            <p>{{ rec.username }}</p>
          </a>
        </div>
      {% endfor %}
    </div>
  {% endif %}
</div>
{% endblock %}""",
    "edit_post.html": edit_post_template,
    "dm_inbox.html":"""{% extends "base.html" %}
{% block content %}
<style>
  /* Options menu styles (unchanged) */
  .dm-options-menu {
    display: none;
    position: absolute;
    right: 0;
    top: 30px;
    background: #fff;
    border: 1px solid #ccc;
    border-radius: 4px;
    min-width: 150px;
    z-index: 1000;
  }
  .dm-options-menu a {
    display: block;
    padding: 8px 12px;
    text-decoration: none;
    color: #333;
  }
  .dm-options-menu a:hover {
    background: #f0f0f0;
  }
  body.dark .dm-options-menu {
    background: #333;
    border-color: #555;
  }
  body.dark .dm-options-menu a {
    color: #ddd;
  }
  body.dark .dm-options-menu a:hover {
    background: #444;
  }
  .dm-options-btn {
    color: inherit;
  }
  /* DM search container */
  .dm-search-container {
    display: flex;
    justify-content: center;
    align-items: center;
    max-width: 500px;
    margin: 0 auto;
  }
  .dm-search-container form {
    flex: 1;
  }
  .dm-search-container input[type="text"] {
    width: 100%;
    padding: 8px 12px;
    border: 1px solid #ccc;
    border-radius: 20px;
  }
  .lock-btn {
    margin-left: 10px;
    background: none;
    border: none;
    cursor: pointer;
    font-size: 24px;
    color: #3897f0;
  }
  /* Lock Modal styles – Instagram-inspired and consistent in light/dark */
  .modal {
    display: none;
    position: fixed;
    z-index: 2000;
    left: 0;
    top: 0;
    background-color: rgba(0,0,0,0.8);
  }
  .modal-content-lock {
    background: #fff;
    width: 90%;
    max-width: 350px;
    margin: 20% auto;
    padding: 30px 20px;
    border-radius: 12px;
    box-shadow: 0 0 15px rgba(0,0,0,0.2);
    text-align: center;
    position: relative;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #262626;
  }
  body.dark .modal-content-lock {
    background: #181818;
    color: #e0e0e0;
    border: 1px solid #333;
  }
  .modal-content-lock h3 {
    margin: 0 0 20px;
    font-size: 1.2rem;
  }
  .modal-content-lock input[type="text"] {
    width: 100%;
    padding: 12px 15px;
    margin-bottom: 20px;
    border: 1px solid #dbdbdb;
    border-radius: 8px;
    font-size: 0.9rem;
    background-color: #fafafa;
  }
  body.dark .modal-content-lock input[type="text"] {
    background-color: #262626;
    border: 1px solid #444;
    color: #e0e0e0;
  }
  .modal-content-lock button {
    width: 100%;
    padding: 12px 0;
    background-color: #3897f0;
    border: none;
    border-radius: 8px;
    color: #fff;
    font-size: 1rem;
    cursor: pointer;
    transition: background 0.3s;
  }
  .modal-content-lock button:hover {
    background-color: #3180d1;
  }
  .modal-content-lock .close {
    position: absolute;
    top: 10px;
    right: 15px;
    font-size: 1.5rem;
    color: #999;
    cursor: pointer;
  }
  .modal-content-lock .close:hover {
    color: #666;
  }
</style>

<div class="dm-container" style="max-width: 800px; margin: 20px auto; padding: 0 15px;">
  <!-- DM Header with Title and Search -->
  <div class="dm-header" style="text-align: center; margin-bottom: 20px;">
    <h2 style="margin-bottom: 10px;">Direct Messages</h2>
    <div class="dm-search-container">
      <!-- Main search box for DM search using "q" -->
      <form id="dm-search-form" action="{{ url_for('dm_inbox') }}" method="GET">
        <input type="text" name="q" placeholder="Search conversations" value="{{ request.args.get('q', '') }}">
        <input type="hidden" name="tab" value="{{ tab }}">
      </form>
      <!-- Lock button to trigger keypass popup -->
      <button id="lock-btn" class="lock-btn">
        <i class="fas fa-lock"></i>
      </button>
    </div>
  </div>
  
  <!-- Lock Popup Modal -->
  <div id="lock-modal" class="modal">
    <div class="modal-content-lock">
      <span class="close" id="lock-close">&times;</span>
      <h3>Enter DM Keypass</h3>
      <form id="lock-form" action="{{ url_for('dm_inbox') }}" method="GET">
        <!-- Preserve current search and tab parameters -->
        <input type="hidden" name="q" value="{{ request.args.get('q', '') }}">
        <input type="hidden" name="tab" value="{{ tab }}">
        <input type="text" name="key" placeholder="Your DM Keypass">
        <button type="submit">Submit</button>
      </form>
    </div>
  </div>
  
  <!-- DM Tabs: Primary, General, Requests -->
  <div class="dm-tabs" style="display: flex; justify-content: space-around; max-width: 500px; margin: 0 auto 20px auto; border-bottom: 1px solid #ccc;">
    <a href="{{ url_for('dm_inbox', tab='primary') }}" class="dm-tab {% if tab=='primary' %}active{% endif %}"
       style="flex: 1; text-align: center; padding: 10px 0; text-decoration: none; color: {% if tab=='primary' %}#3897f0{% else %}#555{% endif %};
              border-bottom: {% if tab=='primary' %}2px solid #3897f0{% else %}none{% endif %};">
      Primary
    </a>
    <a href="{{ url_for('dm_inbox', tab='general') }}" class="dm-tab {% if tab=='general' %}active{% endif %}"
       style="flex: 1; text-align: center; padding: 10px 0; text-decoration: none; color: {% if tab=='general' %}#3897f0{% else %}#555{% endif %};
              border-bottom: {% if tab=='general' %}2px solid #3897f0{% else %}none{% endif %};">
      General
    </a>
    <a href="{{ url_for('dm_inbox', tab='requests') }}" class="dm-tab {% if tab=='requests' %}active{% endif %}"
       style="flex: 1; text-align: center; padding: 10px 0; text-decoration: none; color: {% if tab=='requests' %}#3897f0{% else %}#555{% endif %};
              border-bottom: {% if tab=='requests' %}2px solid #3897f0{% else %}none{% endif %};">
      Requests
    </a>
  </div>
  
  <!-- Conversation List (non-hidden) -->
  <div class="dm-conversations">

  <!-- Hidden Conversations -->
  {% if hidden_conversations %}
    <div class="dm-hidden" style="margin-top: 30px;">
      <h3 style="margin-bottom: 15px;">Hidden Chats</h3>
      {% for convo in hidden_conversations %}
        <div class="dm-conversation" style="display: flex; align-items: center; justify-content: space-between; padding: 12px; border-bottom: 1px solid #eaeaea; position: relative;">
          <a href="{{ url_for('view_dm', convo_id=convo.id) }}" style="flex: 1; text-decoration: none; color: inherit;">
            <div class="dm-convo-info" style="display: flex; align-items: center;">
              {% if current_user.id == convo.participant1_id %}
                {% set partner = convo.participant2 %}
              {% else %}
                {% set partner = convo.participant1 %}
              {% endif %}
              <img src="{{ url_for('static', filename='uploads/' ~ partner.profile_pic) if partner.profile_pic else url_for('static', filename='uploads/default_profile.png') }}"
                   alt="{{ partner.username }}'s profile picture"
                   style="width: 50px; height: 50px; border-radius: 50%; object-fit: cover; margin-right: 12px;">
              <div>
                <h4 style="margin: 0;">{{ partner.username }}</h4>
                <p style="margin: 0; font-size: 12px; color: #888;">Last updated: {{ convo.last_updated.strftime("%Y-%m-%d %H:%M") }}</p>
              </div>
            </div>
          </a>
          <div class="dm-convo-options" style="position: relative;">
            <button class="dm-options-btn" onclick="event.preventDefault(); event.stopPropagation(); toggleDmOptions(this)" style="background: none; border: none; font-size: 20px; cursor: pointer;">⋮</button>
            <div class="dm-options-menu">
              {% if convo.category == 'primary' %}
                <a href="{{ url_for('move_to_general', convo_id=convo.id) }}">Move to General</a>
              {% else %}
                <a href="{{ url_for('move_to_primary', convo_id=convo.id) }}">Move to Primary</a>
              {% endif %}
              <a href="{{ url_for('pin_dm', convo_id=convo.id) }}">
                {% if convo.pinned %}Unpin{% else %}Pin{% endif %}
              </a>
              <a href="{{ url_for('mute_dm', convo_id=convo.id) }}">
                {% if convo.muted %}Unmute{% else %}Mute{% endif %}
              </a>
              <a href="{{ url_for('unhide_chat', convo_id=convo.id) }}">Unhide Chat</a>
            </div>
          </div>
        </div>
      {% endfor %}
    </div>
  {% endif %}

  
    {% if conversations %}
    <br><h3 style="margin-bottom: 15px;">Chats</h3>
      {% for convo in conversations %}
        <div class="dm-conversation" style="display: flex; align-items: center; justify-content: space-between; padding: 12px; border-bottom: 1px solid #eaeaea; position: relative;">
          <!-- Conversation info wrapped in anchor -->
          <a href="{{ url_for('view_dm', convo_id=convo.id) }}" style="flex: 1; text-decoration: none; color: inherit;">
            <div class="dm-convo-info" style="display: flex; align-items: center;">
              {% if current_user.id == convo.participant1_id %}
                {% set partner = convo.participant2 %}
              {% else %}
                {% set partner = convo.participant1 %}
              {% endif %}
              <img src="{{ url_for('static', filename='uploads/' ~ partner.profile_pic) if partner.profile_pic else url_for('static', filename='uploads/default_profile.png') }}"
                   alt="{{ partner.username }}'s profile picture"
                   style="width: 50px; height: 50px; border-radius: 50%; object-fit: cover; margin-right: 12px;">
              <div>
                <h4 style="margin: 0;">{{ partner.username }}</h4>
                <p style="margin: 0; font-size: 12px; color: #888;">Last updated: {{ convo.last_updated.strftime("%Y-%m-%d %H:%M") }}</p>
              </div>
            </div>
          </a>
          <!-- Options button outside the anchor -->
          <div class="dm-convo-options" style="position: relative;">
            <button class="dm-options-btn" onclick="event.preventDefault(); event.stopPropagation(); toggleDmOptions(this)" style="background: none; border: none; font-size: 20px; cursor: pointer;">⋮</button>
            <div class="dm-options-menu">
              {% if convo.category == 'primary' %}
                <a href="{{ url_for('move_to_general', convo_id=convo.id) }}">Move to General</a>
              {% else %}
                <a href="{{ url_for('move_to_primary', convo_id=convo.id) }}">Move to Primary</a>
              {% endif %}
              <a href="{{ url_for('pin_dm', convo_id=convo.id) }}">
                {% if convo.pinned %}Unpin{% else %}Pin{% endif %}
              </a>
              <a href="{{ url_for('delete_dm', convo_id=convo.id) }}">Delete</a>
              <a href="{{ url_for('mute_dm', convo_id=convo.id) }}">
                {% if convo.muted %}Unmute{% else %}Mute{% endif %}
              </a>
              <a href="{{ url_for('hide_chat', convo_id=convo.id) }}">Hide Chat</a>
            </div>
          </div>
        </div>
      {% endfor %}
    {% else %}
      <p style="text-align: center; color: #888;">No conversations found.</p>
    {% endif %}
  </div>
</div>

<script>
  function toggleDmOptions(button) {
    var menu = button.nextElementSibling;
    if (menu.style.display === "block") {
      menu.style.display = "none";
    } else {
      var allMenus = document.querySelectorAll('.dm-options-menu');
      allMenus.forEach(function(m) { m.style.display = "none"; });
      menu.style.display = "block";
    }
  }
  
  // Lock button event listeners for the modal
  document.getElementById("lock-btn").addEventListener("click", function(e) {
    e.preventDefault();
    e.stopPropagation();
    document.getElementById("lock-modal").style.display = "block";
  });
  document.getElementById("lock-close").addEventListener("click", function(e) {
    document.getElementById("lock-modal").style.display = "none";
  });
  window.addEventListener("click", function(e) {
    var modal = document.getElementById("lock-modal");
    if (e.target == modal) {
      modal.style.display = "none";
    }
  });
  
  window.addEventListener('click', function(e) {
    if (!e.target.matches('.dm-options-btn')) {
      var menus = document.querySelectorAll('.dm-options-menu');
      menus.forEach(function(menu) {
        menu.style.display = "none";
      });
    }
  });
</script>
{% endblock %}



""",
    "dm_view.html":"""{% extends "base.html" %}
{% block content %}
<div class="dm-view-container" style="max-width: 800px; margin: 20px auto; background-color: var(--card-bg, #fff); border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); overflow: hidden;">
  <!-- DM Header -->
  <div class="dm-header" style="display: flex; align-items: center; padding: 15px; border-bottom: 1px solid var(--border-color, #ddd); background-color: var(--header-bg, #f8f8f8);">
    {% if current_user.id == conversation.participant1_id %}
      {% set partner = conversation.participant2 %}
    {% else %}
      {% set partner = conversation.participant1 %}
    {% endif %}
    <img src="{{ url_for('static', filename='uploads/' ~ partner.profile_pic) if partner.profile_pic else url_for('static', filename='uploads/default_profile.png') }}"
         alt="{{ partner.username }}'s profile picture"
         style="width: 50px; height: 50px; border-radius: 50%; object-fit: cover; margin-right: 15px;">
    <div style="flex: 1;">
      <h2 style="margin: 0; font-size: 1.25rem;">{{ partner.username }}</h2>
    </div>
    <!-- Action Icons (e.g. Video Call, Info) -->
    <div class="dm-actions" style="display: flex; gap: 10px;">
      <a href="#" style="text-decoration: none; color: var(--icon-color, #3897f0); font-size: 1.2rem;"><i class="fas fa-video"></i></a>
      <a href="#" style="text-decoration: none; color: var(--icon-color, #3897f0); font-size: 1.2rem;"><i class="fas fa-info-circle"></i></a>
    </div>
  </div>
  <!-- Messages Area -->
  <div class="dm-messages" id="dm-messages" style="padding: 20px; height: 500px; overflow-y: auto; background-color: var(--message-bg, #fafafa);">
    {% for msg in messages %}
      {% if msg.sender_id == current_user.id %}
      <div class="dm-message sent" style="text-align: right; margin-bottom: 15px;">
        <div style="display: inline-block; background-color: var(--sent-bg, #3897f0); color: #fff; padding: 10px 15px; border-radius: 20px; max-width: 70%; font-size: 0.95rem;">
          {{ msg.content }}
        </div>
        <div style="font-size: 0.75rem; color: var(--timestamp-color, #ccc); margin-top: 4px;">
          {{ msg.timestamp.strftime("%H:%M") }}
        </div>
      </div>
      {% else %}
      <div class="dm-message received" style="text-align: left; margin-bottom: 15px;">
        <div style="display: inline-block; background-color: var(--received-bg, #e0e0e0); color: #000; padding: 10px 15px; border-radius: 20px; max-width: 70%; font-size: 0.95rem;">
          {{ msg.content }}
        </div>
        <div style="font-size: 0.75rem; color: var(--timestamp-color, #999); margin-top: 4px;">
          {{ msg.timestamp.strftime("%H:%M") }}
        </div>
      </div>
      {% endif %}
    {% endfor %}
  </div>
  <!-- Input Area -->
  <div class="dm-input" style="padding: 15px; border-top: 1px solid var(--border-color, #ddd); background-color: var(--header-bg, #f8f8f8);">
    <form method="POST" style="display: flex; align-items: center;">
      <input type="text" name="content" placeholder="Message..." required 
             style="flex: 1; padding: 12px; border: 1px solid var(--border-color, #ccc); border-radius: 20px; font-size: 1rem; background-color: var(--input-bg, #fff); color: inherit;">
      <button type="submit" style="margin-left: 10px; padding: 12px 20px; background-color: var(--button-bg, #3897f0); border: none; border-radius: 20px; color: #fff; font-size: 1rem;">Send</button>
    </form>
  </div>
</div>
<script>
  // Auto-scroll messages to the bottom on load
  window.onload = function() {
    var messagesDiv = document.getElementById('dm-messages');
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
  };
</script>
{% endblock %}

""",
    "reels.html" : """
{% extends "base.html" %}
{% block content %}
<div id="reelsContainer" style="scroll-snap-type: y mandatory; overflow-y: scroll; height: 100vh;">
  {% for post in posts %}
    <div class="enhanced-post-card" style="scroll-snap-align: start;">
      <!-- Use your post card snippet (possibly a slightly modified version for reels) -->
      {{ post.content }}
      <!-- Render video media without controls, see next snippet -->
    </div>
  {% endfor %}
</div>
{% endblock %}
"""
})

# -----------------------
# Routes
# -----------------------

@app.route('/')
@login_required
def index():
    posts = Post.query.filter_by(archived=False, deleted=False).order_by(Post.timestamp.desc()).all()
    return render_template("index.html", posts=posts)

@app.route('/foryou')
@login_required
def for_you():
    followed_ids = [u.id for u in current_user.followed] + [current_user.id]
    posts = Post.query.filter(Post.user_id.in_(followed_ids)).filter_by(archived=False, deleted=False).order_by(Post.timestamp.desc()).all()
    return render_template("foryou.html", posts=posts)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            flash('Invalid username or password')
    return render_template("login.html")

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        if User.query.filter((User.username==username) | (User.email==email)).first():
            flash('Username or email already exists')
            return redirect(url_for('register'))
        new_user = User(username=username, email=email)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        flash('Registration successful, please login')
        return redirect(url_for('login'))
    return render_template("register.html")

@app.route('/profile/<username>')
@login_required
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    # Adjust posts query: normal posts (non-reposts)
    posts = Post.query.filter_by(user_id=user.id, is_repost=False, archived=False, deleted=False).order_by(Post.timestamp.desc()).all()
    # Reposts
    reposts = Post.query.filter_by(user_id=user.id, is_repost=True, archived=False, deleted=False).order_by(Post.timestamp.desc()).all()
    # User's comments
    comments = Comment.query.filter_by(user_id=user.id).order_by(Comment.timestamp.desc()).all()
    # Only show posts if public or allowed
    if user.is_private and (current_user not in user.followers and current_user.username != user.username):
        posts = []
        reposts = []
        comments = []
    pending_request = None
    if user.is_private and current_user.username != user.username:
        pending_request = FollowRequest.query.filter_by(requester_id=current_user.id, target_id=user.id).first()
    return render_template("profile.html", user=user, posts=posts, reposts=reposts, comments=comments, pending_request=pending_request)


@app.route('/profile/<username>/settings', methods=['GET', 'POST'])
@login_required
def profile_settings(username):
    if username != current_user.username:
        flash("Access denied.")
        return redirect(url_for('profile', username=username))
    if request.method == 'POST':
        current_user.is_private = True if request.form.get('is_private') else False

        profile_pic = request.files.get('profile_pic')
        if profile_pic and allowed_file(profile_pic.filename):
            filename = f"{current_user.username}_{datetime.utcnow().timestamp()}_{profile_pic.filename}"
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            profile_pic.save(filepath)
            current_user.profile_pic = filename

        current_user.bio = request.form.get('bio')
        
        # Debug: Print the dm_keypass from the form
        dm_key = request.form.get('dm_keypass')
        print("DM Key from form:", dm_key)
        current_user.dm_keypass = dm_key

        db.session.commit()
        flash("Settings updated.")
        return redirect(url_for('profile_settings', username=username))

    
    archived_posts = Post.query.filter_by(user_id=current_user.id, archived=True).order_by(Post.timestamp.desc()).all()
    liked_posts = current_user.liked_posts.all()
    # Query for recently deleted posts (ensure your Post model has 'deleted' and 'deleted_at' fields)
    recently_deleted = Post.query.filter_by(user_id=current_user.id, deleted=True).order_by(Post.deleted_at.desc()).all()
    
    return render_template("settings.html", user=current_user, 
                           archived_posts=archived_posts, 
                           liked_posts=liked_posts,
                           recently_deleted=recently_deleted)


@app.route('/new_post', methods=['GET', 'POST'])
@login_required
def new_post():
    if request.method == 'POST':
        content = request.form.get('content')
        media_files = request.files.getlist('media')  # Get multiple files
        filenames = []
        video_thumbs = []
        for media in media_files:
            if media and allowed_file(media.filename):
                # Generate a unique filename
                unique_name = f"{current_user.username}_{datetime.utcnow().timestamp()}_{media.filename}"
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
                media.save(filepath)
                
                # If the file is a video, extract a thumbnail
                if unique_name.lower().endswith(('.mp4', '.mov')):
                    try:
                        clip = VideoFileClip(filepath)
                        thumb_time = clip.duration * 0.1  # 10% into the video
                        video_thumb = f"{current_user.username}_{datetime.utcnow().timestamp()}_thumb.jpg"
                        thumb_path = os.path.join(app.config['UPLOAD_FOLDER'], video_thumb)
                        clip.save_frame(thumb_path, t=thumb_time)
                        clip.reader.close()  
                        if clip.audio:
                            clip.audio.reader.close_proc()
                        video_thumbs.append(video_thumb)
                    except Exception as e:
                        print("Error extracting video thumbnail:", e)
                filenames.append(unique_name)
        # Join multiple filenames (using a delimiter unlikely to appear in filenames)
        media_filenames_str = "||".join(filenames) if filenames else None
        video_thumbs_str = "||".join(video_thumbs) if video_thumbs else None
        
        post = Post(content=content, media_filename=media_filenames_str, video_thumbnail=video_thumbs_str, author=current_user)
        db.session.add(post)
        db.session.commit()
        flash("Post created.")
        return redirect(url_for('index'))
    return render_template("new_post.html")



# New Route: Post Detail Page that shows the post on top and all its comments recursively.
@app.route('/post/<int:post_id>', methods=['GET', 'POST'])
@login_required
def post_detail(post_id):
    post = Post.query.get_or_404(post_id)
    parent_comment_id = request.args.get('parent', None)
    parent_comment = None
    if parent_comment_id:
        parent_comment = Comment.query.get(parent_comment_id)
    if request.method == 'POST':
        content = request.form['content']
        media = request.files.get('media')
        filename = None
        if media and allowed_file(media.filename):
            filename = f"{current_user.username}_{datetime.utcnow().timestamp()}_{media.filename}"
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            media.save(filepath)
        comment = Comment(content=content, media_filename=filename, author=current_user, post=post)
        if request.form.get('parent_id'):
            parent_comment_post = Comment.query.get(request.form.get('parent_id'))
            if parent_comment_post:
                comment.parent = parent_comment_post
        db.session.add(comment)
        db.session.commit()
        flash("Comment added.")
        return redirect(url_for('post_detail', post_id=post.id))
    return render_template("post_detail.html", post=post, parent_comment_id=parent_comment_id, parent_comment=parent_comment)


@app.route('/repost/<int:post_id>')
@login_required
def repost(post_id):
    original = Post.query.get_or_404(post_id)
    repost = Post(
        content=original.content,
        media_filename=original.media_filename,
        video_thumbnail=original.video_thumbnail,
        author=current_user,
        parent=original,
        is_repost=True  # Mark as repost
    )
    db.session.add(repost)
    db.session.commit()
    flash("Post reposted.")
    return redirect(url_for('index'))


@app.route('/delete_post/<int:post_id>')
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        flash("You cannot delete this post.")
        return redirect(url_for('profile', username=current_user.username))
    # Soft delete the post
    post.deleted = True
    post.deleted_at = datetime.utcnow()
    db.session.commit()
    flash("Post moved to Recently Deleted.")
    return redirect(request.referrer or url_for('profile', username=current_user.username))

@app.route('/restore_post/<int:post_id>')
@login_required
def restore_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        flash("You cannot restore this post.")
        return redirect(url_for('profile', username=current_user.username))
    post.deleted = False
    post.deleted_at = None
    db.session.commit()
    flash("Post restored.")
    return redirect(request.referrer or url_for('profile', username=current_user.username))


@app.route('/permanently_delete_post/<int:post_id>')
@login_required
def permanently_delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        flash("You cannot delete this post permanently.")
        return redirect(url_for('profile', username=current_user.username))
    db.session.delete(post)
    db.session.commit()
    flash("Post permanently deleted.")
    return redirect(url_for('profile', username=current_user.username))



@app.route('/edit_post/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        flash("You cannot edit this post.")
        return redirect(url_for('profile', username=current_user.username))
    if request.method == 'POST':
        post.content = request.form.get('content')
        db.session.commit()
        flash("Post updated.")
        return redirect(url_for('profile', username=current_user.username))
    return render_template("edit_post.html", post=post)

@app.route('/pin_post/<int:post_id>')
@login_required
def pin_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        flash("You cannot pin this post.")
        return redirect(url_for('profile', username=current_user.username))
    post.pinned = not post.pinned
    db.session.commit()
    flash("Post pinned." if post.pinned else "Post unpinned.")
    return redirect(request.referrer or url_for('profile', username=current_user.username))

@app.route('/toggle_comments/<int:post_id>')
@login_required
def toggle_comments(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        flash("You cannot change comment settings for this post.")
        return redirect(url_for('profile', username=current_user.username))
    post.comments_enabled = not post.comments_enabled
    db.session.commit()
    flash("Comments enabled." if post.comments_enabled else "Comments disabled.")
    return redirect(request.referrer or url_for('profile', username=current_user.username))

@app.route('/toggle_like_visibility/<int:post_id>')
@login_required
def toggle_like_visibility(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        flash("You cannot change like count visibility for this post.")
        return redirect(url_for('profile', username=current_user.username))
    post.like_count_visible = not post.like_count_visible
    db.session.commit()
    flash("Like count visible." if post.like_count_visible else "Like count hidden.")
    return redirect(request.referrer or url_for('profile', username=current_user.username))

@app.route('/archive_post/<int:post_id>')
@login_required
def archive_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        flash("You cannot archive this post.")
        return redirect(url_for('profile', username=current_user.username))
    post.archived = not post.archived
    db.session.commit()
    flash("Post archived." if post.archived else "Post unarchived.")
    return redirect(request.referrer or url_for('profile', username=current_user.username))

@app.route('/follow/<username>')
@login_required
def follow(username):
    user = User.query.filter_by(username=username).first_or_404()
    if user == current_user:
        flash("You cannot follow yourself.")
        return redirect(url_for('profile', username=username))
    if not user.is_private:
        if current_user not in user.followers:
            user.followers.append(current_user)
            db.session.commit()
            flash(f"You are now following {username}")
        return redirect(url_for('profile', username=username))
    else:
        existing_request = FollowRequest.query.filter_by(requester_id=current_user.id, target_id=user.id).first()
        if existing_request:
            flash("Follow request already sent.")
        else:
            new_request = FollowRequest(requester_id=current_user.id, target_id=user.id)
            db.session.add(new_request)
            db.session.commit()
            flash("Follow request sent.")
        return redirect(url_for('profile', username=username))

@app.route('/unfollow/<username>')
@login_required
def unfollow(username):
    user = User.query.filter_by(username=username).first_or_404()
    if current_user in user.followers:
        user.followers.remove(current_user)
        db.session.commit()
        flash(f"You have unfollowed {username}")
    return redirect(url_for('profile', username=username))

@app.route('/cancel_request/<username>')
@login_required
def cancel_request(username):
    target = User.query.filter_by(username=username).first_or_404()
    follow_request = FollowRequest.query.filter_by(requester_id=current_user.id, target_id=target.id).first()
    if follow_request:
        db.session.delete(follow_request)
        db.session.commit()
        flash("Follow request cancelled.")
    else:
        flash("No follow request to cancel.")
    return redirect(url_for('profile', username=username))

@app.route('/followers/<username>')
@login_required
def followers_list(username):
    user = User.query.filter_by(username=username).first_or_404()
    followers_list = user.followers.all()
    return render_template("followers_list.html", user=user, followers=followers_list)

@app.route('/following/<username>')
@login_required
def following_list(username):
    user = User.query.filter_by(username=username).first_or_404()
    following_list = user.followed.all()
    return render_template("following_list.html", user=user, following=following_list)

@app.route('/user_posts/<username>')
@login_required
def user_posts(username):
    user = User.query.filter_by(username=username).first_or_404()
    posts = Post.query.filter_by(user_id=user.id).order_by(Post.timestamp.desc()).all()
    return render_template("user_posts.html", user=user, posts=posts)

@app.route('/follow_requests')
@login_required
def follow_requests():
    requests = FollowRequest.query.filter_by(target_id=current_user.id).order_by(FollowRequest.timestamp.desc()).all()
    return render_template("follow_requests.html", requests=requests)

@app.route('/accept_request/<int:request_id>')
@login_required
def accept_request(request_id):
    req = FollowRequest.query.get_or_404(request_id)
    if req.target_id != current_user.id:
        flash("You cannot accept this request.")
        return redirect(url_for('follow_requests'))
    requester = User.query.get(req.requester_id)
    if requester not in current_user.followers:
        current_user.followers.append(requester)
    db.session.delete(req)
    db.session.commit()
    flash(f"You have accepted {requester.username}'s follow request.")
    return redirect(url_for('follow_requests'))

@app.route('/reject_request/<int:request_id>')
@login_required
def reject_request(request_id):
    req = FollowRequest.query.get_or_404(request_id)
    if req.target_id != current_user.id:
        flash("You cannot reject this request.")
        return redirect(url_for('follow_requests'))
    requester = User.query.get(req.requester_id)
    db.session.delete(req)
    db.session.commit()
    flash(f"You have rejected {requester.username}'s follow request.")
    return redirect(url_for('follow_requests'))

@app.route('/search')
@login_required
def search():
    query = request.args.get('q', '')
    results = []
    recommendations = []
    if query:
        results = User.query.filter(User.username.contains(query)).all()
    else:
        # Fetch a few recommended users (excluding the current user)
        recommendations = User.query.filter(User.id != current_user.id).limit(12).all()
    return render_template("search.html", query=query, results=results, recommendations=recommendations)


# Liking Routes
@app.route('/like/<int:post_id>')
@login_required
def like(post_id):
    post = Post.query.get_or_404(post_id)
    if current_user not in post.liked_by:
        post.liked_by.append(current_user)
        db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({"likes": post.liked_by.count(), "liked": True})
    return redirect(request.referrer or url_for('index'))

@app.route('/unlike/<int:post_id>')
@login_required
def unlike(post_id):
    post = Post.query.get_or_404(post_id)
    if current_user in post.liked_by:
        post.liked_by.remove(current_user)
        db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({"likes": post.liked_by.count(), "liked": False})
    return redirect(request.referrer or url_for('index'))

@app.route('/repost_comment/<int:comment_id>')
@login_required
def repost_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)

    # Create a new post that correctly references the original comment
    new_post = Post(
        content=comment.content,  # Only saving comment text
        media_filename=comment.media_filename,
        author=current_user,  # The user reposting
        parent_id=comment.post_id,  # Link it to the original post
        is_repost=True
    )

    db.session.add(new_post)
    db.session.commit()
    flash("Comment reposted as a new post.")

    return redirect(url_for('index'))

from sqlalchemy import or_, and_
from sqlalchemy.orm import aliased

@app.route('/dm')
@login_required
def dm_inbox():
    tab = request.args.get('tab', 'primary')
    key_param = request.args.get('key')
    query = request.args.get('q')  # Use "q" solely for search

    # Base query: all conversations involving the current user.
    base = Conversation.query.filter(
        or_(
            Conversation.participant1_id == current_user.id,
            Conversation.participant2_id == current_user.id
        )
    )

    # If a search query is provided, filter by the partner's username.
    if query:
        # Build two separate queries and union them.
        q1 = Conversation.query.filter(
            Conversation.participant1_id == current_user.id,
            Conversation.participant2_id.in_(
                db.session.query(User.id).filter(User.username.ilike('%' + query + '%'))
            )
        )
        q2 = Conversation.query.filter(
            Conversation.participant2_id == current_user.id,
            Conversation.participant1_id.in_(
                db.session.query(User.id).filter(User.username.ilike('%' + query + '%'))
            )
        )
        base = q1.union(q2)

    # Filter by DM tab.
    if tab == 'primary':
        base = base.filter_by(category='primary', dm_pending=False)
    elif tab == 'general':
        base = base.filter_by(category='general', dm_pending=False)
    elif tab == 'requests':
        base = base.filter_by(dm_pending=True)

    # Filter hidden conversations using the per-user hidden state.
    # Assume your Conversation model now has a hidden_by field storing comma-separated user IDs.
    user_id_str = str(current_user.id)
    if key_param and current_user.dm_keypass and key_param == current_user.dm_keypass:
        hidden_convos = base.filter(Conversation.hidden_by.ilike('%' + user_id_str + '%')).all()
    else:
        hidden_convos = []
    
    non_hidden = base.filter(~Conversation.hidden_by.ilike('%' + user_id_str + '%')).all()

    return render_template("dm_inbox.html", conversations=non_hidden, hidden_conversations=hidden_convos, tab=tab)




@app.route('/dm/<int:convo_id>/move_to_general')
@login_required
def move_to_general(convo_id):
    convo = Conversation.query.get_or_404(convo_id)
    if current_user.id not in [convo.participant1_id, convo.participant2_id]:
        flash("Access denied.")
        return redirect(url_for('dm_inbox'))
    convo.category = 'general'
    db.session.commit()
    flash("Conversation moved to General.")
    return redirect(url_for('dm_inbox'))

@app.route('/dm/<int:convo_id>/move_to_primary')
@login_required
def move_to_primary(convo_id):
    convo = Conversation.query.get_or_404(convo_id)
    if current_user.id not in [convo.participant1_id, convo.participant2_id]:
        flash("Access denied.")
        return redirect(url_for('dm_inbox'))
    convo.category = 'primary'
    db.session.commit()
    flash("Conversation moved to Primary.")
    return redirect(url_for('dm_inbox'))

@app.route('/dm/<int:convo_id>/pin')
@login_required
def pin_dm(convo_id):
    convo = Conversation.query.get_or_404(convo_id)
    if current_user.id not in [convo.participant1_id, convo.participant2_id]:
        flash("Access denied.")
        return redirect(url_for('dm_inbox'))
    convo.pinned = not convo.pinned
    db.session.commit()
    flash("Conversation pinned." if convo.pinned else "Conversation unpinned.")
    return redirect(url_for('dm_inbox'))

@app.route('/dm/<int:convo_id>/delete')
@login_required
def delete_dm(convo_id):
    convo = Conversation.query.get_or_404(convo_id)
    if current_user.id not in [convo.participant1_id, convo.participant2_id]:
        flash("Access denied.")
        return redirect(url_for('dm_inbox'))
    # Soft-delete by marking the conversation as hidden
    convo.hidden = True
    db.session.commit()
    flash("Conversation hidden. Use your DM keypass to view hidden chats.")
    return redirect(url_for('dm_inbox'))

@app.route('/dm/<int:convo_id>/mute')
@login_required
def mute_dm(convo_id):
    convo = Conversation.query.get_or_404(convo_id)
    if current_user.id not in [convo.participant1_id, convo.participant2_id]:
        flash("Access denied.")
        return redirect(url_for('dm_inbox'))
    convo.muted = not convo.muted
    db.session.commit()
    flash("Conversation muted." if convo.muted else "Conversation unmuted.")
    return redirect(url_for('dm_inbox'))


@app.route('/dm/new/<username>', methods=['GET', 'POST'])
@login_required
def new_dm(username):
    recipient = User.query.filter_by(username=username).first_or_404()

    # Check mutual follow status correctly
    current_followed_ids = [u.id for u in current_user.followed.all()]
    recipient_followed_ids = [u.id for u in recipient.followed.all()]  # Corrected to recipient's followed list

    # Determine if the DM should be pending
    new_pending = not (recipient.id in current_followed_ids and current_user.id in recipient_followed_ids)

    # Find or create conversation
    conversation = Conversation.query.filter(
        or_(
            (Conversation.participant1_id == current_user.id) & (Conversation.participant2_id == recipient.id),
            (Conversation.participant1_id == recipient.id) & (Conversation.participant2_id == current_user.id)
        )
    ).first()

    if conversation:
        conversation.dm_pending = False
        conversation.category ='primary'
        db.session.commit()
    else:
        # Create new conversation with correct pending status
        conversation = Conversation(
            participant1_id=current_user.id,
            participant2_id=recipient.id,
            dm_pending=new_pending,
            category='requests' if new_pending else 'primary'
        )
        db.session.add(conversation)
        db.session.commit()

    return redirect(url_for('view_dm', convo_id=conversation.id))





@app.route('/dm/view/<int:convo_id>', methods=['GET', 'POST'])
@login_required
def view_dm(convo_id):
    conversation = Conversation.query.get_or_404(convo_id)
    if current_user.id not in [conversation.participant1_id, conversation.participant2_id]:
        flash("Access denied.")
        return redirect(url_for('dm_inbox'))
    
    if request.method == 'POST':
        content = request.form.get('content', '').strip()
        if content:
            message = Message(
                conversation_id=conversation.id,
                sender_id=current_user.id,
                content=content
            )
            db.session.add(message)
            # Only clear pending if the current user is NOT the initiator
            if conversation.dm_pending and current_user.id != conversation.participant1_id:
                conversation.dm_pending = False
                conversation.category = 'primary'
            db.session.commit()
            flash("Message sent.")
            return redirect(url_for('view_dm', convo_id=conversation.id))
    
    messages = Message.query.filter_by(conversation_id=conversation.id)\
                            .order_by(Message.timestamp.asc()).all()
    return render_template("dm_view.html", conversation=conversation, messages=messages)



@app.route('/dm/<int:convo_id>/hide')
@login_required
def hide_chat(convo_id):
    convo = Conversation.query.get_or_404(convo_id)
    if current_user.id not in [convo.participant1_id, convo.participant2_id]:
        flash("Access denied.")
        return redirect(url_for('dm_inbox'))
    # Get current hidden_by list as a list of strings.
    hidden_list = convo.hidden_by.split(',') if convo.hidden_by else []
    if str(current_user.id) not in hidden_list:
        hidden_list.append(str(current_user.id))
    convo.hidden_by = ','.join(hidden_list)
    db.session.commit()
    flash("Chat hidden for you.")
    return redirect(url_for('dm_inbox'))


@app.route('/dm/<int:convo_id>/unhide')
@login_required
def unhide_chat(convo_id):
    convo = Conversation.query.get_or_404(convo_id)
    if current_user.id not in [convo.participant1_id, convo.participant2_id]:
        flash("Access denied.")
        return redirect(url_for('dm_inbox'))
    hidden_list = convo.hidden_by.split(',') if convo.hidden_by else []
    if str(current_user.id) in hidden_list:
        hidden_list.remove(str(current_user.id))
    convo.hidden_by = ','.join(hidden_list)
    db.session.commit()
    flash("Chat unhidden for you.")
    return redirect(url_for('dm_inbox'))

@app.route('/load_posts')
def load_posts():
    offset = int(request.args.get('offset', 0))
    posts = Post.query.order_by(Post.timestamp.desc()).offset(offset).limit(10).all()
    # Render and return a snippet of post cards (for example, via a partial template)
    return render_template('post_cards.html', posts=posts)

@app.route('/reels')
@login_required
def reels():
    video_posts = Post.query.filter(Post.media_filename.contains('.mp4')).order_by(Post.timestamp.desc()).all()
    return render_template('reels.html', posts=video_posts)



# -----------------------
# Main execution
# -----------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    #public_url = ngrok.connect(5000)
    #print(" * ngrok tunnel \"{}\" -> \"http://127.0.0.1:5000\"".format(public_url))
    app.run(host='0.0.0.0', port=5000, debug=True)
