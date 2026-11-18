"""使用公开数据执行轻量兼容性检查，输出省略凭证。
Run small compatibility checks with public data and omit credentials from output.
"""
from pathlib import Path
import sys
import json
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database.session import configured_database_url
from llm_gateway import structured_client

def main():
    rows = []
    schema = {'type':'object','additionalProperties':False,'properties':{'summary':{'type':'string'}},'required':['summary']}
    for task in ('sentiment', 'advice', 'review', 'vision'):
        client = structured_client(task)
        if client is None:
            rows.append(dict(task=task,status='missing-key')); continue
        started = time.monotonic()
        try:
            content = 'Summarize: a hypothetical public company reports higher revenue. Do not add facts.'
            if task == 'vision':
                from PIL import Image, ImageDraw
                from io import BytesIO
                import base64
                picture = Image.new('RGB',(320,160),'white')
                ImageDraw.Draw(picture).line([(20,130),(100,80),(200,100),(300,30)],fill='blue',width=3)
                buffer = BytesIO(); picture.save(buffer,format='PNG')
                content = [{'type':'text','text':'Describe this synthetic line chart; do not infer numeric values.'},
                           {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()}}]
            result = client.responses.create(input=[{'role':'user','content':content}],
                text={'format':{'type':'json_schema','name':'probe','strict':True,'schema':schema}},max_output_tokens=1000)
            rows.append(dict(task=task,status='ok',model=result.model,elapsed_seconds=round(time.monotonic()-started,2)))
        except Exception as error:
            rows.append(dict(task=task,status='failed',error=type(error).__name__))
    print(json.dumps(rows,indent=2))
    return int(any(r['status'] != 'ok' for r in rows))

if __name__ == '__main__':raise SystemExit(main())
