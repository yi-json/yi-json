import datetime
from dateutil import relativedelta
import requests
import os
from lxml import etree
import time

HEADERS = {'authorization': 'token '+ os.environ['ACCESS_TOKEN']}
USER_NAME = os.environ['USER_NAME']
QUERY_COUNT = {'user_getter': 0, 'follower_getter': 0, 'graph_repos_stars': 0, 'graph_commits': 0}


def daily_readme(birthday):
    """
    Returns the length of time since I was born
    e.g. 'XX years, XX months, XX weeks'
    """
    diff = relativedelta.relativedelta(datetime.datetime.today(), birthday)
    weeks = diff.days // 7
    return '{} {}, {} {}, {} {}{}'.format(
        diff.years, 'year' + format_plural(diff.years), 
        diff.months, 'month' + format_plural(diff.months), 
        weeks, 'week' + format_plural(weeks),
        ' 🎂' if (diff.months == 0 and weeks == 0) else '')


def format_plural(unit):
    """
    Returns a properly formatted number
    e.g.
    'day' + format_plural(diff.days) == 5
    >>> '5 days'
    'day' + format_plural(diff.days) == 1
    >>> '1 day'
    """
    return 's' if unit != 1 else ''


def simple_request(func_name, query, variables):
    """
    Returns a request, or raises an Exception if the response does not succeed.
    """
    request = requests.post('https://api.github.com/graphql', json={'query': query, 'variables':variables}, headers=HEADERS)
    if request.status_code == 200:
        return request
    raise Exception(func_name, ' has failed with a', request.status_code, request.text, QUERY_COUNT)


def graph_commits(start_date, end_date):
    """
    Uses GitHub's GraphQL v4 API to return my total commit count
    """
    query_count('graph_commits')
    query = '''
    query($start_date: DateTime!, $end_date: DateTime!, $login: String!) {
        user(login: $login) {
            contributionsCollection(from: $start_date, to: $end_date) {
                contributionCalendar {
                    totalContributions
                }
            }
        }
    }'''
    variables = {'start_date': start_date,'end_date': end_date, 'login': USER_NAME}
    request = simple_request(graph_commits.__name__, query, variables)
    return int(request.json()['data']['user']['contributionsCollection']['contributionCalendar']['totalContributions'])


def graph_repos_stars(count_type, owner_affiliation, cursor=None):
    """
    Uses GitHub's GraphQL v4 API to return my total repository, star, or lines of code count.
    """
    query_count('graph_repos_stars')
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: $owner_affiliation) {
                totalCount
                edges {
                    node {
                        ... on Repository {
                            nameWithOwner
                            stargazers {
                                totalCount
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }'''
    variables = {'owner_affiliation': owner_affiliation, 'login': USER_NAME, 'cursor': cursor}
    request = simple_request(graph_repos_stars.__name__, query, variables)
    if request.status_code == 200:
        if count_type == 'repos':
            return request.json()['data']['user']['repositories']['totalCount']
        elif count_type == 'stars':
            return stars_counter(request.json()['data']['user']['repositories']['edges'])


def stars_counter(data):
    """
    Count total stars in repositories owned by me
    """
    total_stars = 0
    for node in data: total_stars += node['node']['stargazers']['totalCount']
    return total_stars


def svg_overwrite(filename, age_data, commit_data, star_data, repo_data, contrib_data, follower_data):
    """
    Parse SVG files and update elements with my age, commits, stars, and repositories
    Aligns the GitHub Stats lines so | and right edge are consistent
    """
    tree = etree.parse(filename)
    root = tree.getroot()
    
    # Format numbers with commas
    repo_str = f"{repo_data:,}"
    contrib_str = f"{contrib_data:,}"
    star_str = f"{star_data:,}"
    commit_str = f"{commit_data:,}"
    follower_str = f"{follower_data:,}"
    
    # Line 1: . Repos:[dots]repo {Contributed: contrib} | Stars:[dots]star
    # Line 2: . Commits:[dots]commit | Followers:[dots]follower
    
    # For | alignment: left sides must be equal width
    # Line 1 left fixed: ". Repos:" (8) + " {Contributed: " (15) + "}" (1) = 24
    # Line 2 left fixed: ". Commits:" (10)
    # Difference = 14 + len(repo) + len(contrib) - len(commit)
    
    # For right edge alignment: "Followers:" is 4 chars longer than "Stars:"
    # So: star_dots = follower_dots + 4
    
    # Use minimum dots for repo (4 chars = " .. ")
    repo_dots = 4
    
    # commit_dots must compensate for the difference in left side fixed content
    # 24 + len(repo) + len(contrib) + repo_dots = 10 + len(commit) + commit_dots
    commit_dots = 24 + len(repo_str) + len(contrib_str) + repo_dots - 10 - len(commit_str)
    commit_dots = max(4, commit_dots)
    
    # For right side alignment with minimum follower_dots
    follower_dots = 8
    star_dots = follower_dots + 4  # compensate for "Followers:" being 4 chars longer
    
    # Helper to create dot string (n is total length including spaces)
    def make_dots(n):
        if n <= 0:
            return ' '
        elif n == 1:
            return ' '
        elif n == 2:
            return '. '
        else:
            return ' ' + '.' * (n - 2) + ' '
    
    # Update all elements
    find_and_replace(root, 'repo_data', repo_str)
    find_and_replace(root, 'repo_data_dots', make_dots(repo_dots))
    find_and_replace(root, 'contrib_data', contrib_str)
    find_and_replace(root, 'star_data', star_str)
    find_and_replace(root, 'star_data_dots', make_dots(star_dots))
    find_and_replace(root, 'commit_data', commit_str)
    find_and_replace(root, 'commit_data_dots', make_dots(commit_dots))
    find_and_replace(root, 'follower_data', follower_str)
    find_and_replace(root, 'follower_data_dots', make_dots(follower_dots))
    
    tree.write(filename, encoding='utf-8', xml_declaration=True)


def justify_format(root, element_id, new_text, length=0):
    """
    Updates and formats the text of the element, and modifes the amount of dots in the previous element to justify the new text on the svg
    """
    if isinstance(new_text, int):
        new_text = f"{'{:,}'.format(new_text)}"
    new_text = str(new_text)
    find_and_replace(root, element_id, new_text)
    just_len = max(0, length - len(new_text))
    if just_len <= 2:
        dot_map = {0: '', 1: ' ', 2: '. '}
        dot_string = dot_map[just_len]
    else:
        dot_string = ' ' + ('.' * just_len) + ' '
    find_and_replace(root, f"{element_id}_dots", dot_string)


def find_and_replace(root, element_id, new_text):
    """
    Finds the element in the SVG file and replaces its text with a new value
    """
    element = root.find(f".//*[@id='{element_id}']")
    if element is not None:
        element.text = new_text


def user_getter(username):
    """
    Returns the account ID and creation time of the user
    """
    query_count('user_getter')
    query = '''
    query($login: String!){
        user(login: $login) {
            id
            createdAt
        }
    }'''
    variables = {'login': username}
    request = simple_request(user_getter.__name__, query, variables)
    return {'id': request.json()['data']['user']['id']}, request.json()['data']['user']['createdAt']

def follower_getter(username):
    """
    Returns the number of followers of the user
    """
    query_count('follower_getter')
    query = '''
    query($login: String!){
        user(login: $login) {
            followers {
                totalCount
            }
        }
    }'''
    request = simple_request(follower_getter.__name__, query, {'login': username})
    return int(request.json()['data']['user']['followers']['totalCount'])


def query_count(funct_id):
    """
    Counts how many times the GitHub GraphQL API is called
    """
    global QUERY_COUNT
    QUERY_COUNT[funct_id] += 1


def perf_counter(funct, *args):
    """
    Calculates the time it takes for a function to run
    Returns the function result and the time differential
    """
    start = time.perf_counter()
    funct_return = funct(*args)
    return funct_return, time.perf_counter() - start


def formatter(query_type, difference, funct_return=False, whitespace=0):
    """
    Prints a formatted time differential
    Returns formatted result if whitespace is specified, otherwise returns raw result
    """
    print('{:<23}'.format('   ' + query_type + ':'), sep='', end='')
    print('{:>12}'.format('%.4f' % difference + ' s ')) if difference > 1 else print('{:>12}'.format('%.4f' % (difference * 1000) + ' ms'))
    if whitespace:
        return f"{'{:,}'.format(funct_return): <{whitespace}}"
    return funct_return


if __name__ == '__main__':
    """
    Adapted from Andrew Grant's (Andrew6rant) script for yi-json
    """
    print('Calculation times:')
    # define global variable for owner ID
    user_data, user_time = perf_counter(user_getter, USER_NAME)
    OWNER_ID, _ = user_data
    formatter('account data', user_time)
    age_data, age_time = perf_counter(daily_readme, datetime.datetime(2003, 12, 16))
    formatter('age calculation', age_time)
    from datetime import timedelta
    end_date = datetime.datetime.now().isoformat() + 'Z'
    start_date = (datetime.datetime.now() - timedelta(days=365)).isoformat() + 'Z'
    commit_data, commit_time = perf_counter(graph_commits, start_date, end_date)
    formatter('commits (last year)', commit_time)
    star_data, star_time = perf_counter(graph_repos_stars, 'stars', ['OWNER'])
    repo_data, repo_time = perf_counter(graph_repos_stars, 'repos', ['OWNER'])
    contrib_data, contrib_time = perf_counter(graph_repos_stars, 'repos', ['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'])
    follower_data, follower_time = perf_counter(follower_getter, USER_NAME)

    svg_overwrite('dark_mode.svg', age_data, commit_data, star_data, repo_data, contrib_data, follower_data)
    svg_overwrite('light_mode.svg', age_data, commit_data, star_data, repo_data, contrib_data, follower_data)

    print('\033[F\033[F\033[F\033[F\033[F\033[F',
        '{:<21}'.format('Total function time:'), '{:>11}'.format('%.4f' % (user_time + age_time + commit_time + star_time + repo_time + contrib_time)),
        ' s \033[E\033[E\033[E\033[E\033[E\033[E', sep='')

    print('Total GitHub GraphQL API calls:', '{:>3}'.format(sum(QUERY_COUNT.values())))
    for funct_name, count in QUERY_COUNT.items(): print('{:<28}'.format('   ' + funct_name + ':'), '{:>6}'.format(count))

