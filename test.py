import base64
import os

import cv2
import numpy as np
import requests
from flask import Flask, jsonify, render_template, request
from pyzbar.pyzbar import decode

API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY", "AIzaSyAOqaDwXsMRWuj5C5OkvdftJNxSJ8c7bv0")

app = Flask(__name__)


def normalize_isbn(isbn):
    return "".join(ch for ch in str(isbn) if ch.isdigit() or ch.upper() == "X")


def decode_barcode_from_image(image_bytes):
    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

    if frame is None:
        return None

    barcodes = decode(frame)
    if len(barcodes) == 0:
        return None

    return barcodes[0].data.decode("utf-8")


def fetch_book_info(isbn):
    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}&key={API_KEY}"
    response = requests.get(url, timeout=15)
    response.raise_for_status()

    data = response.json()
    if data.get("totalItems", 0) == 0:
        return None

    info = data["items"][0]["volumeInfo"]
    return {
        "title": info.get("title"),
        "authors": ", ".join(info.get("authors", [])),
        "publisher": info.get("publisher"),
        "publishedDate": info.get("publishedDate"),
        "categories": ", ".join(info.get("categories", [])),
        "isbn": isbn,
        "cover": info.get("imageLinks", {}).get("thumbnail"),
        "description": info.get("description", "-"),
    }


def fetch_book_info_perpusnas(isbn):
    normalized_isbn = normalize_isbn(isbn)
    if not normalized_isbn:
        return None

    params = {
        "search": normalized_isbn,
        "filter_by": "code",
        "jenis_media": "all",
        "by_penerbit": "",
        "by_kota": "",
        "draw": "1",
        "start": "0",
        "length": "10",
    }

    response = requests.get(
        "https://isbn.perpusnas.go.id/landing_page/serverside_search2",
        params=params,
        timeout=15,
    )
    response.raise_for_status()

    data = response.json()
    rows = data.get("data", [])
    if not rows:
        return None

    selected_row = None
    for row in rows:
        row_code = normalize_isbn(row.get("code", ""))
        row_isbn = normalize_isbn(row.get("isbn", ""))
        if row_code == normalized_isbn or row_isbn == normalized_isbn:
            selected_row = row
            break

    if selected_row is None:
        selected_row = rows[0]

    return {
        "title": selected_row.get("title") or "-",
        "authors": "-",
        "publisher": selected_row.get("nama_penerbit") or "-",
        "publishedDate": selected_row.get("tahun_terbit") or "-",
        "categories": ", ".join(
            part
            for part in [
                selected_row.get("jenis_media"),
                selected_row.get("jenis_kategori"),
                selected_row.get("tempat_terbit"),
            ]
            if part
        )
        or "-",
        "isbn": selected_row.get("isbn") or selected_row.get("code") or isbn,
        "cover": None,
        "description": "Sumber: Perpusnas RI",
        "source": "perpusnas",
    }


def resolve_book_info(isbn):
    google_book = fetch_book_info(isbn)
    if google_book:
        google_book["source"] = "google_books"
        return google_book

    perpusnas_book = fetch_book_info_perpusnas(isbn)
    if perpusnas_book:
        return perpusnas_book

    return None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/scan", methods=["POST"])
def scan():
    payload = request.get_json(silent=True) or {}
    image_data = payload.get("image")

    if not image_data:
        return jsonify({"ok": False, "message": "Gambar tidak diterima."}), 400

    if "," in image_data:
        image_data = image_data.split(",", 1)[1]

    try:
        image_bytes = base64.b64decode(image_data)
    except ValueError:
        return jsonify({"ok": False, "message": "Format gambar tidak valid."}), 400

    isbn = decode_barcode_from_image(image_bytes)
    if not isbn:
        return jsonify({"ok": False, "message": "Barcode tidak ditemukan."}), 404

    try:
        book = resolve_book_info(isbn)
    except requests.RequestException as exc:
        return jsonify({"ok": False, "message": f"Error saat mengambil data buku: {exc}"}), 502

    if not book:
        return jsonify({"ok": True, "isbn": isbn, "book": None, "message": "Buku tidak ditemukan di Google Books maupun Perpusnas."})

    return jsonify({"ok": True, "isbn": isbn, "book": book})


@app.route("/lookup", methods=["POST"])
def lookup():
    payload = request.get_json(silent=True) or {}
    isbn = str(payload.get("isbn", "")).strip()

    if not isbn:
        return jsonify({"ok": False, "message": "ISBN tidak boleh kosong."}), 400

    try:
        book = resolve_book_info(isbn)
    except requests.RequestException as exc:
        return jsonify({"ok": False, "message": f"Error saat mengambil data buku: {exc}"}), 502

    if not book:
        return jsonify({"ok": True, "isbn": isbn, "book": None, "message": "Buku tidak ditemukan di Google Books maupun Perpusnas."})

    return jsonify({"ok": True, "isbn": isbn, "book": book})


if __name__ == "__main__":
    app.run(debug=True)