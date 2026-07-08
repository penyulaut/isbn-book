from __future__ import annotations

import os
import re
from pathlib import Path

import cv2
import numpy as np
import requests
from flask import Flask, jsonify, request, send_from_directory
from dotenv import load_dotenv
from pyzbar.pyzbar import decode

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

GOOGLE_BOOKS_API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY", "").strip()


def clean_isbn(value: str) -> str:
    return re.sub(r"[^0-9Xx]", "", value or "").upper()


def decode_barcode(image: np.ndarray) -> str | None:
    candidates = [image]

    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image

    larger = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    larger_3x = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    thresholded = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    adaptive = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        11,
    )
    equalized = cv2.equalizeHist(gray)
    sharpen_kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
    sharpened = cv2.filter2D(gray, -1, sharpen_kernel)

    height, width = gray.shape[:2]
    center_crop = gray[
        int(height * 0.15) : int(height * 0.85),
        int(width * 0.08) : int(width * 0.92),
    ]
    center_crop_large = cv2.resize(center_crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

    candidates.extend(
        [
            gray,
            larger,
            larger_3x,
            blurred,
            thresholded,
            adaptive,
            equalized,
            sharpened,
            center_crop,
            center_crop_large,
        ]
    )

    variants = []
    for candidate in candidates:
        variants.append(candidate)
        variants.append(cv2.rotate(candidate, cv2.ROTATE_90_CLOCKWISE))
        variants.append(cv2.rotate(candidate, cv2.ROTATE_90_COUNTERCLOCKWISE))
        variants.append(cv2.rotate(candidate, cv2.ROTATE_180))

    for candidate in variants:
        for barcode in decode(candidate):
            decoded = barcode.data.decode("utf-8", errors="ignore").strip()
            isbn = clean_isbn(decoded)
            if isbn:
                return isbn

    return None


def fetch_book_info(isbn: str) -> dict:
    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"
    if GOOGLE_BOOKS_API_KEY:
        url += f"&key={GOOGLE_BOOKS_API_KEY}"

    response = requests.get(url, timeout=15)
    response.raise_for_status()
    data = response.json()

    if data.get("totalItems", 0) == 0:
        return {"found": False}

    volume_info = data["items"][0]["volumeInfo"]
    return {
        "found": True,
        "title": volume_info.get("title"),
        "authors": volume_info.get("authors", []),
        "publisher": volume_info.get("publisher"),
        "publishedDate": volume_info.get("publishedDate"),
        "categories": volume_info.get("categories", []),
        "cover": volume_info.get("imageLinks", {}).get("thumbnail"),
    }


@app.get("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.post("/scan")
def scan():
    file = request.files.get("image")
    if not file:
        return jsonify(success=False, message="File gambar tidak ditemukan."), 400

    file_name = (file.filename or "").lower()
    file_bytes = np.frombuffer(file.read(), np.uint8)
    image = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)

    if image is None:
        return jsonify(success=False, message="Gambar tidak valid atau tidak bisa dibaca."), 400

    isbn = decode_barcode(image)
    if not isbn:
        center = image[
            int(image.shape[0] * 0.15) : int(image.shape[0] * 0.85),
            int(image.shape[1] * 0.08) : int(image.shape[1] * 0.92),
        ]
        isbn = decode_barcode(center)

    if not isbn and ("full" in file_name or "frame" in file_name):
        isbn = decode_barcode(image)

    if not isbn:
        return jsonify(success=False, message="Barcode belum terbaca dari gambar."), 200

    try:
        book = fetch_book_info(isbn)
    except requests.RequestException as exc:
        return (
            jsonify(success=False, message=f"Gagal mengambil data buku: {exc}", isbn=isbn),
            502,
        )

    if not book.get("found"):
        return jsonify(success=False, message="ISBN terbaca, tetapi buku tidak ditemukan.", isbn=isbn), 200

    return jsonify(success=True, isbn=isbn, book=book)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
