from flask import Flask
from sender import check_pixiv  # 你的主函数

app = Flask(__name__)

@app.route('/trigger')
def trigger():
    check_pixiv()
    return "Executed successfully", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))