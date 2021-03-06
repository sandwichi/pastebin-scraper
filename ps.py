#!/usr/bin/env python3

__version__ = '0.2'
__author__ = 'Dan Hollis'

import os
import sys
import traceback

from datetime import datetime
from flask import Flask
from flask import render_template
from flask import request
from getpass import getpass
from glob import glob
from sqlalchemy import func
from threading import Thread

from modules.flask.models import AdditionalKeywords
from modules.flask.models import Projects
from modules.flask.models import ScrapeHistory
from modules.flask.models import db
from modules.lib.colors import colors
from modules.lib.config import Config
from modules.lib.output import Output
from modules.scraper.core import run_scraper

# Load configs
config_file = Config(os.path.join(os.path.split(os.path.realpath(__file__))[0], 'config.ini'))
scraper_config = config_file.scraper_config()
flask_config = config_file.flask_config()
if flask_config['env'] == 'dev':
	password = getpass('Enter database password: ')
elif flask_config['env'] == 'prod':
	password = flask_config['password']
else:
	print('{1}{2}[!] Invalid value {3} given to env setting in [flask] section of config.ini.{0}\n'.format(colors.RESET, colors.BOLD, colors.RED, flask_config['env']))
	sys.exit('{1}{2}[*] Must be either prod or dev. If using prod the database password must be hardcoded in the password option of the [flask] section.{0}'.format(colors.RESET, colors.BOLD, colors.YELLOW))
database_config = config_file.database_config(password)

app = Flask(__name__, template_folder="modules/flask/templates")
app.config['SECRET_KEY'] = flask_config['secret_key']
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://{0}:{1}@{2}/{3}'.format('scraper', password, database_config['host'], 'pastebin_scraper')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = True

db.init_app(app)

@app.route('/', methods=['GET', 'POST'])
def index():
	if request.method == 'POST':
		try:
			if 'searchProject' in request.form:
				project_name = request.form['searchProject']
				if not project_name:
					option = request.form.getlist('otherSearchRadio')
					if not option:
						return render_template('index.html', messages=['error', ['No project name given', 'No options selected']])
					if option[0] == 'listProject':
						project_query_all = db.session.query(Projects).all()
						if project_query_all:
							active_projects = ['{0}'.format(pa.project_name) for pa in project_query_all if pa.active]
							inactive_projects = ['{0} (inactive)'.format(pi.project_name) for pi in project_query_all if not pi.active]
							results = ['listProj', 'Currently exisiting project names:', active_projects, inactive_projects]
							return render_template('index.html', results=results)
						return render_template('index.html', results=['listProj', 'No projects currently exist'])
					else:
						cross_project_query = db.session.query(AdditionalKeywords).filter(AdditionalKeywords.additional_keyword_id == 1).first()
						if cross_project_query:
							current_additional_keywords = cross_project_query.additional_keywords
							results = ['listKw', 'Current cross project keywords:', current_additional_keywords]
							return render_template('index.html', results=results)
						return render_template('index.html', results=['listKw', 'No cross project keywords currently exist'])
				project_query = db.session.query(Projects).filter(func.lower(Projects.project_name) == project_name.lower()).first()
				if not project_query:
					return render_template('index.html', messages=['error', ['No data found for project {0}'.format(project_name), 'Project does not exist']])
				results = [project_query.project_name, project_query.keywords, project_query.found_keywords, project_query.active]
				return render_template('index.html', results=results)
			elif 'outputProject' in request.form:
				project_name = request.form['outputProject']
				output_types = request.form.getlist('outputCheck')
				if not project_name:
					return render_template('index.html', messages=['error', ['No project name supplied']])
				if not output_types:
					return render_template('index.html', messages=['error', ['No output type selected']])
				project_query = db.session.query(Projects).filter(func.lower(Projects.project_name) == project_name.lower()).first()
				if not project_query:
					return render_template('index.html', messages=['error', ['No data found for project {0}'.format(project_name), 'Project does not exist']])
				if not project_query.found_keywords:
					return render_template('index.html', messages=['error', ['No data found for project {0}'.format(project_query.project_name)]])
				try:
					if flask_config['env'] == 'prod':
						output_dir = ('/var/www/pastebin-scraper/outputs/{0}'.format(project_query.project_name))
					else:
						if request.form['outputDir']:
							output_dir = os.path.abspath(request.form['outputDir'])
						else:
							output_dir = os.path.join(os.path.split(os.path.realpath(__file__))[0], 'outputs/{0}'.format(project_query.project_name))
					if not os.path.exists(output_dir):
						os.makedirs(output_dir)
					outputs = []
					output_file_path = '{0}/{1}_{2}'.format(output_dir, project_query.project_name, datetime.now().strftime('%m%d%Y'))
					if 'csv' in output_types or 'all' in output_types:
						file_exists = glob('{0}*.csv'.format(output_file_path))
						if file_exists:
							current_files = glob('{0}_*.csv'.format(output_file_path))
							if not current_files:
								path_with_ext = '{0}_1.csv'.format(output_file_path)
							else:
								newest_file = max([int(os.path.split(f)[1].split('_')[-1].split('.')[0]) for f in current_files])
								path_with_ext = '{0}_{1}.csv'.format(output_file_path, newest_file + 1)
						else:
							path_with_ext = '{0}.csv'.format(output_file_path)
						output_file = Output(path_with_ext, project_query)
						output_file.csv_output()
						outputs.append(path_with_ext)
					if 'json' in output_types or 'all' in output_types:
						file_exists = glob('{0}*.json'.format(output_file_path))
						if file_exists:
							current_files = glob('{0}_*.json'.format(output_file_path))
							if not current_files:
								path_with_ext = '{0}_1.json'.format(output_file_path)
							else:
								newest_file = max([int(os.path.split(f)[1].split('_')[-1].split('.')[0]) for f in current_files])
								path_with_ext = '{0}_{1}.json'.format(output_file_path, newest_file + 1)
						else:
							path_with_ext = '{0}.json'.format(output_file_path)
						output_file = Output(path_with_ext, project_query)
						output_file.json_output()
						outputs.append(path_with_ext)
				except PermissionError:
					return render_template('index.html', messages=['error', ['You don\'t have permission to access directory:', '{0}'.format(output_dir)]])
				except Exception:
					return render_template('error.html', errors=traceback.format_exception(*sys.exc_info()))
				return render_template('index.html', messages=['info', ['Output saved to:', '{0}'.format('<br>'.join(outputs))]])
			elif 'createProject' in request.form:
				project_name = request.form['createProject']
				keywords = [kw.strip() for kw in request.form['keywords'].split(',')]
				if not project_name or not request.form['keywords']:
					return render_template('index.html', messages=['error', ['All fields required']])
				if '' in keywords:
					return render_template('index.html', messages=['error', ['No blanks allowed in keywords', 'e.g. word1, ,word2']])
				project_query = db.session.query(Projects).filter(func.lower(Projects.project_name) == project_name.lower()).first()
				if project_query:
					results = [project_query.project_name, project_query.keywords, project_query.found_keywords, project_query.active]
					return render_template('index.html', results=results, messages=['error', ['Project {0} already exists'.format(results[0])]])
				project = Projects(project_name, list(sorted(set(keywords))), [], active=True)
				db.session.add(project)
				db.session.commit()
				return render_template('index.html', messages=['info', ['Created project {0}'.format(project_name)]])
			elif 'updateProject' in request.form:
				if not request.form['addKeywords'] and not request.form['removeKeywords']:
					return render_template('index.html', messages=['error', ['No keywords supplied']])
				project_name = request.form['updateProject']
				add_keywords = ''
				remove_keywords = ''
				if request.form['addKeywords']:
					add_keywords = [add_kw.strip() for add_kw in request.form['addKeywords'].split(',')]
					if '' in add_keywords:
						return render_template('index.html', messages=['error', ['No blanks allowed in keywords', 'e.g. word1, ,word2']])
				if request.form['removeKeywords']:
					remove_keywords = [remove_kw.strip() for remove_kw in request.form['removeKeywords'].split(',')]
					if '' in remove_keywords:
						return render_template('index.html', messages=['error', ['No blanks allowed in keywords', 'e.g. word1, ,word2']])
				if (add_keywords or remove_keywords) and not project_name:
					return render_template('index.html', messages=['error', ['All fields required']])
				project_query = db.session.query(Projects).filter(func.lower(Projects.project_name) == project_name.lower()).first()
				if not project_query:
					return render_template('index.html', messages=['error', ['No data found for project {0}'.format(project_name), 'Project does not exist']])
				current_keywords = project_query.keywords
				if add_keywords:
					current_keywords = current_keywords + [add_kw for add_kw in add_keywords if add_kw not in current_keywords]
					project_query.keywords = list(sorted(set(current_keywords)))
					db.session.commit()
				if remove_keywords:
					if not set(remove_keywords).issubset(current_keywords):
						return render_template('index.html', messages=['error', ['Keywords were entered to be removed that do not exist for project {0}', 
							'Search for the project to check it\'s keywords.'.format(project_query.project_name)]])
					new_keywords = [remove_kw for remove_kw in current_keywords if remove_kw not in remove_keywords]
					project_query.keywords = sorted(new_keywords)
					db.session.commit()
				return render_template('index.html', messages=['info', ['Updated project {0}'.format(project_query.project_name)]])
			elif 'updateProjStatus' in request.form:
				option = request.form.getlist('updateStatusRadio')
				project_name = request.form['updateProjStatus']
				if not project_name:
					return render_template('index.html', messages=['error', ['No project name given']])
				if not option:
					return render_template('index.html', messages=['error', ['No status update selected']])
				project_query = db.session.query(Projects).filter(func.lower(Projects.project_name) == project_name.lower()).first()
				if not project_query:
					return render_template('index.html', messages=['error', ['No data found for project {0}'.format(project_name), 'Project does not exist']])
				if option[0] == 'delete':
					project_id = project_query.project_id
					Projects.query.filter_by(project_id=project_id).delete()
					db.session.commit()
					return render_template('index.html', messages=['info', ['Deleted project {0}'.format(project_query.project_name)]])
				elif option[0] == 'deactivate':
					if not project_query.active:
						return render_template('index.html', messages=['error', ['Project {0} is already deactivated'.format(project_query.project_name)]])
					project_query.active = False
					db.session.commit()
					return render_template('index.html', messages=['info', ['Deactivated project {0}'.format(project_query.project_name)]])
				else:
					if project_query.active:
						return render_template('index.html', messages=['error', ['Project {0} is already activated'.format(project_query.project_name)]])
					project_query.active = True
					db.session.commit()
					return render_template('index.html', messages=['info', ['Reactivated project {0}'.format(project_query.project_name)]])
			elif 'addCrossProjectKeywords' in request.form:
				if not request.form['addCrossProjectKeywords']:
					return render_template('index.html', messages=['error', ['All fields required']])
				keywords = list(sorted(set([kw.strip() for kw in request.form['addCrossProjectKeywords'].split(',')])))
				if '' in keywords:
					return render_template('index.html', messages=['error', ['No blanks allowed in keywords', 'e.g. word1, ,word2']])
				cross_project_query = db.session.query(AdditionalKeywords).filter(AdditionalKeywords.additional_keyword_id == 1).first()
				if not cross_project_query:
					additional_keywords = AdditionalKeywords(keywords)
					db.session.add(additional_keywords)
					db.session.commit()
					return render_template('index.html', messages=['info', ['Updated cross project keywords']])
				current_additional_keywords = cross_project_query.additional_keywords + [kw for kw in keywords if kw not in cross_project_query.additional_keywords]
				cross_project_query.additional_keywords = list(sorted(set(current_additional_keywords)))
				db.session.commit()
				return render_template('index.html', messages=['info', ['Updated cross project keywords']])
			elif 'removeCrossProjectKeywords' in request.form:
				if not request.form['removeCrossProjectKeywords']:
					return render_template('index.html', messages=['error', ['All fields required']])
				keywords = [kw.strip() for kw in request.form['removeCrossProjectKeywords'].split(',')]
				cross_project_query = db.session.query(AdditionalKeywords).filter(AdditionalKeywords.additional_keyword_id == 1).first()
				current_additional_keywords = cross_project_query.additional_keywords
				if not cross_project_query or not current_additional_keywords:
					return render_template('index.html', messages=['error', ['No cross project keywords found']])
				if not set(keywords).issubset(current_additional_keywords):
					not_found = [kw.strip() for kw in keywords if kw not in current_additional_keywords and kw != '']
					results = ['listKw', 'Current cross project keywords:<br>', current_additional_keywords]
					return render_template('index.html', results=results, messages=['error', ['Cross project keywords were entered to be removed that do not exist in the database:', '<br>'.join(not_found)]])
				current_additional_keywords = [kw for kw in current_additional_keywords if kw not in keywords]
				cross_project_query.additional_keywords = current_additional_keywords
				db.session.commit()
				return render_template('index.html', messages=['info', ['Updated cross project keywords']])
		except Exception:
			return render_template('error.html', errors=traceback.format_exception(*sys.exc_info()))
	return render_template('index.html')

if __name__ == '__main__':
	try:
		print('Scraping...')
		if flask_config['env'] == 'dev':
			scrape_thread = Thread(target=run_scraper, args=(database_config, scraper_config))
			scrape_thread.daemon = True
			scrape_thread.start()
			app.run(debug=False, host=flask_config['host'], port=flask_config['port'])
		else:
			run_scraper(database_config, scraper_config)
		sys.exit('\nExiting...')
	except KeyboardInterrupt:
		sys.exit('\nExiting...')
	except Exception:
		sys.exit(''.join(traceback.format_exception(*sys.exc_info())))
