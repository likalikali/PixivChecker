from flask import Flask
from sender import check_pixiv  # 你的主函数

app = Flask(__name__)

@app.route('/trigger', methods=['GET'])
def trigger():
    check_pixiv()
    return "Executed", 200

if __name__ == '__main__':
    app.run()  # 本地测试