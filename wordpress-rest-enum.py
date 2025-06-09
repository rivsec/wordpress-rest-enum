# wordpress-rest-enum.py

import requests
import json
import argparse
import logging
import urllib3
import re

urllib3.disable_warnings()

# Argument parsing
parser = argparse.ArgumentParser()
# Argument group, select either website or input file
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument("-w", "--website", help="Website to check.", action='store', type=str)
group.add_argument("-i", "--input-file", help="Input file containing list of websites", type=str)
parser.add_argument_group(group)
parser.add_argument("--log-level", default=logging.ERROR, type=lambda x: getattr(logging, x), help="Configure the logging level.")
parser.add_argument("-m", "--media", help="Fetch media", action=argparse.BooleanOptionalAction, required=False)
parser.add_argument("-po", "--posts", help="Fetch posts", action=argparse.BooleanOptionalAction, required=False)
parser.add_argument("-pa", "--pages", help="Fetch pages", action=argparse.BooleanOptionalAction, required=False)
parser.add_argument("-u", "--users", help="Fetch users", action=argparse.BooleanOptionalAction, required=False)
parser.add_argument("-c", "--comments", help="Fetch comments", action=argparse.BooleanOptionalAction, required=False)
parser.add_argument(
    "-im",
    "--ignoreImages",
    help="Filter out extensions commonly associated with images and video",
    action=argparse.BooleanOptionalAction,
    required=False,
)
parser.add_argument(
    "-be",
    "--block-extensions",
    help="Additional comma-separated file extensions to block (e.g. 'pdf,doc,docx')",
    type=str,
    required=False,
)
parser.add_argument("-o", "--output-file", help="Output file to save the results.", type=str, required=False)

cliArgs = parser.parse_args()

# Logging
logging.basicConfig(level=cliArgs.log_level)

# Globals
HEADERS = {'User-Agent': 'WordPress Testing'}


def requestRESTAPIComments(website: str, fetchPage: int, timeout=10) -> json:
    perPage = 100
    apiRequest = f'{website}/wp-json/wp/v2/comments?per_page={perPage}&page={str(fetchPage)}'
    results = []
    try:
        with requests.Session() as s:
            download = s.get(apiRequest, headers=HEADERS, verify=False, timeout=timeout)
            if download.status_code == 200:
                # WordPress API returns mixed HTML and JSON in the users API endpoint.
                # Remove all content to the first `[` indicating the beginning of JSON data.
                content = '[' + '['.join(download.text.split('[')[1:])
                comments = json.loads(content)
                for comment in comments:
                    try:
                        newComment = {"name": comment['author_name'], "date": comment['date'], "link": comment['link']}
                        results.append(newComment)
                    except Exception as err:
                        print(f"Unexpected {err=}, {type(err)=}")
                        raise
                fetchPage = fetchPage + 1
                if len(comments) > 0:
                    results += requestRESTAPIComments(website, fetchPage)
    except:
        raise

    return results


def requestRESTAPIUsers(website: str, fetchPage: int, timeout=10) -> json:
    perPage = 100
    apiRequest = f'{website}/wp-json/wp/v2/users?per_page={perPage}&page={str(fetchPage)}'
    results = []
    try:
        with requests.Session() as s:
            download = s.get(apiRequest, headers=HEADERS, verify=False, timeout=timeout)
            if download.status_code == 200:
                content = download.text
                users = json.loads(content)
                for user in users:
                    try:
                        newUser = {"name": user['name'], "username": user['slug']}
                        results.append(newUser)
                    except Exception as err:
                        print(f"Unexpected {err=}, {type(err)=}")
                        raise
                fetchPage = fetchPage + 1
                if len(users) > 0:
                    results += requestRESTAPIUsers(website, fetchPage)

    except:
        raise
    return results


def requestRESTAPI(type: str, website: str, fetchPage: int, timeout=10) -> list:
    perPage = 100

    try:
        apiRequest = f'{website}/wp-json/wp/v2/{type}?per_page={perPage}&page={str(fetchPage)}'
        results = []
        with requests.Session() as s:
            download = s.get(apiRequest, headers=HEADERS, verify=False, timeout=timeout)
            if download.status_code == 200:
                content = download.text
                if content is not None:
                    apiResponse = json.loads(content)
                    for typeReturn in apiResponse:
                        try:
                            results.append(typeReturn['guid']['rendered'])
                        except Exception as err:
                            print(f"Unexpected {err=}, {type(err)=}")
                            raise
                    fetchPage = fetchPage + 1
                    if len(apiResponse) > 0:
                        results += requestRESTAPI(type, website, fetchPage)
    except:
        raise

    return results


def main():
    websites = []
    if cliArgs.input_file:
        with open(cliArgs.input_file, 'r') as f:
            websites_from_file = f.readlines()
            for website in websites_from_file:
                website = website.strip()
                websites.append(website)
    else:
        websites.append(cliArgs.website)
    fetchPage = 1

    cnt = 0
    try:
        for website in websites:
            result = {}
            result["website"] = website
            found = False
            if cliArgs.posts:
                result["posts"] = requestRESTAPI("posts", website, fetchPage)
                if len(result["posts"]) > 0:
                    found = True
            if cliArgs.pages:
                result["pages"] = requestRESTAPI("pages", website, fetchPage)
                if len(result["pages"]) > 0:
                    found = True
            if cliArgs.comments:
                result["comments"] = requestRESTAPIComments(website, fetchPage)
                if len(result["comments"]) > 0:
                    found = True
            if cliArgs.media:
                result["media"] = requestRESTAPI("media", website, fetchPage)
                if cliArgs.ignoreImages or cliArgs.block_extensions:
                    newMedia = []
                    # Base extensions to ignore if ignoreImages is True
                    extensions_to_ignore = (
                        r'\.(jpg|gif|jpeg|png|svg|tiff|webm|webp|mp4|mov|avif)$' if cliArgs.ignoreImages else ''
                    )

                    # Add additional extensions if specified
                    if cliArgs.block_extensions:
                        additional_extensions = '|'.join(ext.strip() for ext in cliArgs.block_extensions.split(','))
                        if extensions_to_ignore:
                            extensions_to_ignore = f'({extensions_to_ignore}|{additional_extensions})$'
                        else:
                            extensions_to_ignore = f'\.({additional_extensions})$'

                    for url in result['media']:
                        if not re.search(extensions_to_ignore, url, flags=re.IGNORECASE):
                            newMedia.append(url)
                    result["media"] = newMedia
                if len(result["media"]) > 0:
                    found = True
            if cliArgs.users:
                result["users"] = requestRESTAPIUsers(website, fetchPage)
                if len(result["users"]) > 0:
                    found = True
            if not found:
                logging.info(json.dumps({"message": "no results", "target": website}))
            else:
                if cliArgs.output_file:
                    with open(cliArgs.output_file, 'a') as f:
                        if cnt > 0:
                            f.write("\n")
                        f.write(json.dumps(result))
                else:
                    print(json.dumps(result))
            cnt += 1
    except json.JSONDecodeError as e:
        logging.warning(f"JSON decode error {e=}, {type(e)=}")
    except urllib3.exceptions.MaxRetryError as e:
        logging.warning(f"Max retries exceeded {e=}, {type(e)=}")
    except requests.exceptions.ConnectionError as e:
        logging.warning(f"Connection error {e=}, {type(e)=}")
    except requests.exceptions.InvalidSchema as e:
        logging.warning(f"Invalid schema {e=}, {type(e)=}")
    except urllib3.exceptions.ReadTimeoutError as e:
        logging.warning(f"Timeout {e=}, {type(e)=}")
    except Exception as e:
        logging.warning(f"Unexpected {e=}, {type(e)=}")


if __name__ == '__main__':
    main()
