import os, time, base64, json
from openai import OpenAI
import requests
from bs4 import BeautifulSoup
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

def fetch_decoded_batch_execute(id):
    s = (
        '[[["Fbv4je","[\\"garturlreq\\",[[\\"en-US\\",\\"US\\",[\\"FINANCE_TOP_INDICES\\",\\"WEB_TEST_1_0_0\\"],'
        'null,null,1,1,\\"US:en\\",null,180,null,null,null,null,null,0,null,null,[1608992183,723341000]],'
        '\\"en-US\\",\\"US\\",1,[2,3,4,8],1,0,\\"655000234\\",0,0,null,0],\\"'
        + id
        + '\\"]",null,"generic"]]]'
    )

    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        "Referer": "https://news.google.com/",
    }

    response = requests.post(
        "https://news.google.com/_/DotsSplashUi/data/batchexecute?rpcids=Fbv4je",
        headers=headers,
        data={"f.req": s},
    )

    if response.status_code != 200:
        raise Exception("Failed to fetch data from Google.")

    text = response.text
    header = '[\\"garturlres\\",\\"'
    footer = '\\",'
    if header not in text:
        raise Exception(f"Header not found in response: {text}")
    start = text.split(header, 1)[1]
    if footer not in start:
        raise Exception("Footer not found in response.")
    url = start.split(footer, 1)[0]
    return url


def decode_google_news_url(source_url):
    url = requests.utils.urlparse(source_url)
    path = url.path.split("/")
    if url.hostname == "news.google.com" and len(path) > 1 and path[-2] == "articles":
        base64_str = path[-1]
        decoded_bytes = base64.urlsafe_b64decode(base64_str + "==")
        decoded_str = decoded_bytes.decode("latin1")

        prefix = b"\x08\x13\x22".decode("latin1")
        if decoded_str.startswith(prefix):
            decoded_str = decoded_str[len(prefix) :]

        suffix = b"\xd2\x01\x00".decode("latin1")
        if decoded_str.endswith(suffix):
            decoded_str = decoded_str[: -len(suffix)]

        bytes_array = bytearray(decoded_str, "latin1")
        length = bytes_array[0]
        if length >= 0x80:
            decoded_str = decoded_str[2 : length + 1]
        else:
            decoded_str = decoded_str[1 : length + 1]

        if decoded_str.startswith("AU_yqL"):
            return fetch_decoded_batch_execute(base64_str)

        return decoded_str
    else:
        return source_url

def summarize_article(url):
  
  response = requests.get(url)
  
  soup = BeautifulSoup(response.text, 'html.parser')
  content = soup.get_text(separator='\n', strip=True)
  
  retries = 5
  delay = 10 # in seconds
  while retries > 0:
      try:
          # Define the system message
          system_msg = 'You are an AI specialized in summarizing news articles. All your responses are in Korean. You are perfect in summarizing articles when given an url.'

          # Define the user message
          user_msg = 'Give me a summary for the following article: ' + content

          # Create a dataset using GPT
          response = client.chat.completions.create(
              model="gpt-4o-mini",
              messages=[
                  {"role": "system", "content": system_msg},
                  {"role": "user", "content": user_msg, "name": "user"}
              ],
          )

          # Extract the response from the API
          summary = response.choices[0].message.content
          # print("Summary for: " + url + " ->" + summary)

          return summary
      
      except client.error.RateLimitError as e:
          retries -= 1
          if retries == 0:
              print(f"RateLimitError: Maximum retries exceeded for {url}")
              break
          print(f"RateLimitError: Retrying after {delay} seconds for {url}")
          time.sleep(delay)
          delay *= 2

def extract_entities(summary):
    retries = 5
    delay = 10 # in seconds
    while retries > 0:
        try:
            # Define the system message
            system_msg = "You are an AI specialized in entity recognition. For every given Text you give back the most relevant three entities as a comma separated array. Use the base form and singular for each entity"

            # Define the user message
            user_msg = 'Give me the entities for the following text: ' + str(summary)

            # Create a dataset using GPT
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg, "name": "user"}
                ],
            )

            # Extract the response from the API
            entities = response.choices[0].message.content
            # print("Entities for: " + summary + " ->" + entities)

            return entities
        
        except client.error.RateLimitError as e:
            retries -= 1
            if retries == 0:
                print(f"RateLimitError: Maximum retries exceeded for {summary}")
                break
            print(f"RateLimitError: Retrying after {delay} seconds for {summary}")
            time.sleep(delay)
            delay *= 2

def send_slack_message(message):
    try:
        response = slack_client.chat_postMessage(
            channel='ai-daily-news',
            text=message
        )
        return response
    except SlackApiError as e:
        return f"Error sending message: {e.response['error']}"

client = OpenAI()

slack_token = os.environ["SLACK_BOT_TOKEN"]
slack_client = WebClient(token=slack_token)

catch_url = "https://news.google.com/rss/topics/CAAqIAgKIhpDQkFTRFFvSEwyMHZNRzFyZWhJQ1pXNG9BQVAB?hl=en-US&gl=US&ceid=US%3Aen"
search = requests.get(catch_url)

soup = BeautifulSoup(search.content, features = "xml")
items = soup.findAll("item")

i = 0
for item in items:
  url = decode_google_news_url(item.link.text)
  summary = summarize_article(url)
  keywords = extract_entities(summary)
  story = {
      "Headline": item.title.text,
      "Url": url,
      "Pubdate": item.pubDate.text,
      "Source": item.source.text,
      "Domain": item.source["url"],
      "Summary": summary,
      "Keywords": keywords
      
  }
  json_str = json.dumps(story, indent=4, ensure_ascii=False)
  print(json_str)
  send_slack_message(json_str)

  i = i + 1
  if i == 3:
    break
