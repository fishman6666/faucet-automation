from flask import Flask, render_template, request, Response
from concurrent.futures import ThreadPoolExecutor, as_completed
import httpx, time

app = Flask(__name__)

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/run', methods=['POST'])
def run():
    def event_stream(addresses, proxies, client_key):
        website_url = "https://faucet.campnetwork.xyz/"
        website_key = "5b86452e-488a-4f62-bd32-a332445e2f51"
        user_agent = "Mozilla/5.0 ..."

        def parse_proxy_line(line):
            parts = line.strip().split(":")
            return f"socks5://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}" if len(parts)==4 else None

        def process_one(i, addr, proxy_line):
            proxy = parse_proxy_line(proxy_line)
            # 打码 + 领取流程...
            # 返回 f"{i+1}. ✅ {addr}：成功/失败信息"
            return f"{i+1}. ✅ {addr}：done"

        with ThreadPoolExecutor(max_workers=10) as exe:
            futures = [exe.submit(process_one, i, addresses[i], proxies[i]) for i in range(len(addresses))]
            for f in as_completed(futures):
                yield f"data: {f.result()}\n\n"

    addrs = request.form.get('addresses','').splitlines()
    proxies = request.form.get('proxies','').splitlines()
    key = request.form.get('client_key','').strip()
    if not (addrs and proxies and key) or len(addrs)!=len(proxies):
        return "❌ 参数错误",400

    return Response(event_stream(addrs, proxies, key), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(debug=True, threaded=True)
