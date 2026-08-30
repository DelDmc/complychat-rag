import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY =  os.environ.get('SECRET_KEY')

# The `DYNO` env var is set on Heroku CI, but it's not a real Heroku app, so we have to
# also explicitly exclude CI:
# https://devcenter.heroku.com/articles/heroku-ci#immutable-environment-variables
IS_HEROKU_APP = "DYNO" in os.environ and not "CI" in os.environ

# SECURITY WARNING: don't run with debug turned on in production!
# Read DEBUG from the environment and default to OFF. A host that forgets to
# set it then fails safe, instead of serving tracebacks and settings to the
# public. Set DEBUG=1 in src/.env for local development.
DEBUG = os.environ.get("DEBUG", "0").strip().lower() in ("1", "true", "yes", "on")

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS").split(', ')
# On Heroku, it's safe to use a wildcard for `ALLOWED_HOSTS``, since the Heroku router performs
# validation of the Host header in the incoming HTTP request. On other platforms you may need
# to list the expected hostnames explicitly to prevent HTTP Host header attacks. See:
# https://docs.djangoproject.com/en/4.2/ref/settings/#std-setting-ALLOWED_HOSTS
# if IS_HEROKU_APP:
#     ALLOWED_HOSTS = ["*"]
# else:
#     ALLOWED_HOSTS = []

# Application definition

INSTALLED_APPS = [
    # 'django.contrib.admin',
    "whitenoise.runserver_nostatic",
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_extensions',
    'django_filters',
    'rest_framework',
    'app',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    "whitenoise.middleware.WhiteNoiseMiddleware",
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = 'static/'

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


REST_FRAMEWORK = {
    'EXCEPTION_HANDLER': 'rest_framework_json_api.exceptions.exception_handler',
    'DEFAULT_PARSER_CLASSES': (
        'rest_framework_json_api.parsers.JSONParser',
    ),
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework_json_api.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer'
    ),
    'DEFAULT_METADATA_CLASS': 'rest_framework_json_api.metadata.JSONAPIMetadata',
    'DEFAULT_FILTER_BACKENDS': (
        'rest_framework_json_api.filters.QueryParameterValidationFilter',
        'rest_framework_json_api.filters.OrderingFilter',
        'rest_framework_json_api.django_filters.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
    ),
    'SEARCH_PARAM': 'filter[search]',
    'TEST_REQUEST_RENDERER_CLASSES': (
        'rest_framework_json_api.renderers.JSONRenderer',
    ),
    'TEST_REQUEST_DEFAULT_FORMAT': 'vnd.api+json'
}

'''
'EXCEPTION_HANDLER': 'rest_framework_json_api.exceptions.exception_handler':
This setting specifies the custom exception handler to be used by the Django REST framework. 
It tells Django to use the exception_handler function from the rest_framework_json_api.exceptions 
module to handle exceptions raised during API requests.

'DEFAULT_PARSER_CLASSES': ('rest_framework_json_api.parsers.JSONParser',):
This setting defines the default parser classes used for request data parsing. 
In this case, it specifies that the JSONParser from the rest_framework_json_api.parsers 
module should be used to parse incoming JSON data.

'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework.authentication.TokenAuthentication',]:
This setting sets the default authentication classes for API views. 
It includes the TokenAuthentication class from Django REST framework, 
which allows API authentication using tokens.

'DEFAULT_RENDERER_CLASSES': ('rest_framework_json_api.renderers.JSONRenderer', 'rest_framework.renderers.BrowsableAPIRenderer'):
This setting defines the default renderer classes used to render response data. 
It includes the JSONRenderer from the rest_framework_json_api.renderers module, 
which is used to render JSON:API-compliant responses. Additionally, 
it includes the BrowsableAPIRenderer from the rest_framework.renderers module, 
which provides a browsable HTML representation of the API for easy navigation and debugging.

'DEFAULT_METADATA_CLASS': 'rest_framework_json_api.metadata.JSONAPIMetadata':
This setting specifies the default metadata class used to generate metadata for the API responses. 
The JSONAPIMetadata class from the rest_framework_json_api.metadata module is used, 
which generates metadata following the JSON:API specification.

'DEFAULT_FILTER_BACKENDS': ('rest_framework_json_api.filters.QueryParameterValidationFilter', 'rest_framework_json_api.filters.OrderingFilter', 'rest_framework_json_api.django_filters.DjangoFilterBackend', 'rest_framework.filters.SearchFilter'):
This setting defines the default filter backends used for filtering querysets. 
It includes several filter backends related to JSON:API, such as QueryParameterValidationFilter, 
OrderingFilter, DjangoFilterBackend, and the standard SearchFilter.

'SEARCH_PARAM': 'filter[search]':
This setting defines the parameter used for searching in the API. 
It specifies that the search parameter should be passed in the querystring using the filter[search] syntax.

'TEST_REQUEST_RENDERER_CLASSES': ('rest_framework_json_api.renderers.JSONRenderer',):
This setting defines the renderer classes used for rendering test API requests. 
It includes the JSONRenderer to render test requests in JSON:API format.

'TEST_REQUEST_DEFAULT_FORMAT': 'vnd.api+json':
This setting specifies the default format used for test API requests.
It sets the default format to vnd.api+json, which is a media type used in JSON:API.
'''

# LOGGING = {
#     'version': 1,
#     'disable_existing_loggers': False,
#     'handlers': {
#         'console': {
#             'class': 'logging.StreamHandler',
#         },
#     },
#     'loggers': {
#         'django': {
#             'handlers': ['console'],
#             'level': 'DEBUG',
#         },
#     },
# }