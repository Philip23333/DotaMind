
import urllib.request, json
req = urllib.request.Request(
    'http://localhost:8000/api/v1/meta-report',
    data=b'{\"game\":\"dota2\",\"patch\":\"latest\",\"role\":\"offlane\"}',
    headers={'Content-Type': 'application/json'},
    method='POST'
)
r = urllib.request.urlopen(req, timeout=15)
data = json.loads(r.read())
print('source status:', data['sources'][0]['status'])
print()
for h in data['top_heroes'][:5]:
    print(f"{h['hero']:<25} wr={h['win_rate']:.3f}  pick={h['pick_rate']:.4f}  pro={h['pro_presence']:.3f}")
    
print("-"*50)
print(f"h:{data['top_heroes'][:5]}")