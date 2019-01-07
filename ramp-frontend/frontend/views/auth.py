import logging

import flask_login

from flask import Blueprint
from flask import current_app
from flask import flash
from flask import redirect
from flask import request
from flask import render_template
from flask import session
from flask import url_for

from sqlalchemy.orm.exc import NoResultFound

from ramputils.password import check_password
from ramputils.password import hash_password

from rampdb.tools.user import add_user_interaction
from rampdb.tools.user import get_user_by_name
from rampdb.tools.user import set_user_by_instance

from rampdb.model import User

from frontend import db
from frontend import login_manager

from ..forms import LoginForm
from ..forms import UserUpdateProfileForm

logger = logging.getLogger('FRONTEND')
mod = Blueprint('auth', __name__)


@login_manager.user_loader
def load_user(id):
    return User.query.get(id)


@mod.route("/login", methods=['GET', 'POST'])
def login():
    add_user_interaction(db.session, interaction='landing')

    if flask_login.current_user.is_authenticated:
        logger.info('User already logged-in')
        session['logged_in'] = True
        return redirect(url_for('general.problems'))

    form = LoginForm()
    if form.validate_on_submit():
        try:
            user = get_user_by_name(db.session, name=form.user_name.data)
        except NoResultFound:
            msg = u'User "{}" does not exist'.format(form.user_name.data)
            flash(msg)
            logger.info(msg)
            return redirect(url_for('auth.login'))
        if not check_password(form.password.data,
                              user.hashed_password):
            msg = 'Wong password'
            flash(msg)
            logger.info(msg)
            return redirect(url_for('auth.login'))
        flask_login.login_user(user, remember=True)
        session['logged_in'] = True
        user.is_authenticated = True
        db.session.commit()
        logger.info(u'User "{}" is logged in'
                    .format(flask_login.current_user.name))
        add_user_interaction(db.session, interaction='login',
                             user=flask_login.current_user)
        next_ = request.args.get('next')
        if next_ is None:
            next_ = url_for('general.problems')
        return redirect(next_)

    return render_template('login.html', form=form)


@mod.route("/logout")
@flask_login.login_required
def logout():
    user = flask_login.current_user
    add_user_interaction(db.session, interaction='logout', user=user)
    session['logged_in'] = False
    user.is_authenticated = False
    db.session.commit()
    logger.info(u'{} is logged out'.format(user))
    flask_login.logout_user()

    return redirect(url_for('auth.login'))


@mod.route("/update_profile", methods=['GET', 'POST'])
@flask_login.login_required
def update_profile():
    form = UserUpdateProfileForm()
    form.user_name.data = flask_login.current_user.name
    if form.validate_on_submit():
        try:
            set_user_by_instance(
                db.session, flask_login.current_user, form.lastname.data,
                form.firstname.data, form.linkedin_url.data,
                form.twitter_url.data, form.facebook_url.data,
                form.google_url.data, form.github_url.data,
                form.website_url.data, form.bio.data, form.email.data,
                form.is_want_news.data
            )
            # update_user(flask_login.current_user, form)
        except Exception as e:
            flash(u'{}'.format(e), category='Update profile error')
            return redirect(url_for('auth.update_profile'))
        # send_register_request_mail(user)
        return redirect(url_for('general.problems'))
    form.lastname.data = flask_login.current_user.lastname
    form.firstname.data = flask_login.current_user.firstname
    form.email.data = flask_login.current_user.email
    form.linkedin_url.data = flask_login.current_user.linkedin_url
    form.twitter_url.data = flask_login.current_user.twitter_url
    form.facebook_url.data = flask_login.current_user.facebook_url
    form.google_url.data = flask_login.current_user.google_url
    form.github_url.data = flask_login.current_user.github_url
    form.website_url.data = flask_login.current_user.website_url
    form.bio.data = flask_login.current_user.bio
    form.is_want_news.data = flask_login.current_user.is_want_news
    return render_template('update_profile.html', form=form)
