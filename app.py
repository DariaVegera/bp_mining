import os
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from skills.parse_process import parse_process
from skills.generate_bpmn import generate_bpmn

app = Flask(__name__, static_folder="static")
CORS(app)

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json()
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Текст не может быть пустым"}), 400

    try:
        process_json = parse_process(text)
        bpmn_xml = generate_bpmn(process_json)
        return jsonify({
            "bpmn": bpmn_xml,
            "process": process_json
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/update", methods=["POST"])
def update():
    data = request.get_json()
    current_bpmn = data.get("bpmn", "")
    instruction = data.get("instruction", "").strip()
    if not current_bpmn or not instruction:
        return jsonify({"error": "Не хватает данных"}), 400

    try:
        from skills.update_bpmn import update_bpmn
        updated_bpmn = update_bpmn(current_bpmn, instruction)
        return jsonify({"bpmn": updated_bpmn})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print("🚀 BPMN Generator запущен: http://localhost:5000")
    app.run(debug=True, port=5000)
