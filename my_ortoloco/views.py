# -*- coding: utf-8 -*-

from datetime import date
from collections import defaultdict
from StringIO import StringIO
import string
import random
import re
import math
from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import auth
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, login
from django.core.management import call_command

from my_ortoloco.models import *
from my_ortoloco.forms import *
from my_ortoloco.helpers import *
from my_ortoloco.filters import Filter
from my_ortoloco.mailer import *

from static_ortoloco.models import StaticContent

import hashlib
from static_ortoloco.models import Politoloco

from decorators import primary_loco_of_abo


def password_generator(size=8, chars=string.ascii_uppercase + string.digits): return ''.join(random.choice(chars) for x in range(size))

def get_menu_dict(request):
    loco = request.user.loco
    next_jobs = set()
    if loco.abo is not None:
        allebohnen = Boehnli.objects.filter(loco=loco)
        userbohnen = []

        for bohne in allebohnen:
            if bohne.is_boehnli_done():
                userbohnen.append(bohne)

        # amount of beans shown => round up if needed never down
        bohnenrange = range(0, max(userbohnen.__len__(), int(math.ceil(loco.abo.size * 10 / loco.abo.locos.count()))))

        for bohne in Boehnli.objects.all().filter(loco=loco).order_by("job__time"):
            if bohne.job.time > datetime.datetime.now():
                next_jobs.add(bohne.job)
    else:
        bohnenrange = None
        userbohnen = []
        userbohnen_kernbereich = []
        next_jobs = set()

    depot_admin = Depot.objects.filter(contact=request.user)

    return {
        'user': request.user,
        'bohnenrange': bohnenrange,
        'userbohnen_total': len(userbohnen),
        'userbohnen_kernbereich': len([bohne for bohne in userbohnen if bohne.is_in_kernbereich()]),
        'next_jobs': next_jobs,
        'staff_user': request.user.is_staff,
        'depot_admin': depot_admin,
        'politoloco': request.user.has_perm('static_ortoloco.can_send_newsletter')
    }


@login_required
def my_home(request):
    """
    Overview on myortoloco
    """
    
    infos = ""
    if StaticContent.objects.all().filter(name='home_infos').__len__() > 0:
        infos = StaticContent.objects.all().filter(name='home_infos')[0].content + "</br>"

    announcement = ""
    if StaticContent.objects.all().filter(name='my.ortoloco').__len__() > 0:
        announcement = u"<h3>Ankündigungen:</h3>" + StaticContent.objects.all().filter(name='my.ortoloco')[0].content + "</br>"

    next_jobs = set(get_current_jobs()[:7])
    pinned_jobs = set(Job.objects.filter(pinned=True, time__gte=datetime.datetime.now()))
    next_aktionstage = set(Job.objects.filter(typ__name="Aktionstag", time__gte=datetime.datetime.now()).order_by("time")[:2])
    renderdict = get_menu_dict(request)
    renderdict.update({
        'jobs': sorted(next_jobs.union(pinned_jobs).union(next_aktionstage), key=lambda job: job.time),
        'teams': Taetigkeitsbereich.objects.filter(hidden=False),
        'no_abo': request.user.loco.abo is None,
        'announcement': announcement,
        'infos': infos
    })

    return render(request, "myhome.html", renderdict)


@login_required
def my_job(request, job_id):
    """
    Details for a job
    """
    loco = request.user.loco
    job = get_object_or_404(Job, id=int(job_id))

    send_email_allowed = request.user.is_staff

    if request.method == 'POST':
        num = request.POST.get("jobs")
        # adding participants
        add = int(num)
        for i in range(add):
            Boehnli.objects.create(loco=loco, job=job)

    participants_dict = defaultdict(int)
    boehnlis = Boehnli.objects.filter(job_id=job.id)
    number_of_participants = len(boehnlis)

    participants_new_dict = defaultdict(dict)
    recipients_emails = []
    for boehnli in boehnlis:
        if boehnli.loco is not None:
            recipients_emails.append(boehnli.loco.email)
            loco_info = participants_new_dict[boehnli.loco.first_name + ' ' + boehnli.loco.last_name]
            current_count = loco_info.get("count", 0)
            current_msg = loco_info.get("msg", [])
            loco_info["count"] = current_count + 1
            #current_msg.append("boehnli.comment")
            loco_info["msg"] = current_msg

    participants_summary = []
    for loco_name, loco_dict in participants_new_dict.iteritems():
        # print loco_name, loco_dict
        count = loco_dict.get("count")
        msg = loco_dict.get("msg")
        # msg = ", ".join(loco_dict.get("msg"))
        if count == 1:
            participants_summary.append((loco_name, None))
        elif count == 2:
            participants_summary.append((loco_name + ' (mit einer weiteren Person)', msg))
        else:
            participants_summary.append((loco_name
                                                    + ' (mit ' + str(count - 1)
                                                    + ' weiteren Personen)', msg))

    # for boehnli in boehnlis:
    #     if boehnli.loco is not None:
    #         participants_dict[boehnli.loco.first_name + ' ' + boehnli.loco.last_name] += 1

    # participants_summary = []
    # for loco_name, number_of_companions in participants_dict.iteritems():
    #     if number_of_companions == 1:
    #         participants_summary.append(loco_name)
    #     elif number_of_companions == 2:
    #         participants_summary.append(loco_name + ' (mit einer weiteren Person)')
    #     else:
    #         participants_summary.append(loco_name
    #                                     + ' (mit ' + str(number_of_companions - 1)
    #                                     + ' weiteren Personen)')

    slotrange = range(0, job.slots)
    allowed_additional_participants = range(1, job.slots - number_of_participants + 1)

    renderdict = get_menu_dict(request)
    jobendtime = job.end_time()

    renderdict.update({
        'recipients_type': "Teilnehmer dieses Jobs",
        'recipients_emails':  ', '.join(set(recipients_emails)),
        'recipients_count': len(set(recipients_emails)),
        'send_email_allowed': send_email_allowed,

        'number_of_participants': number_of_participants,
        'participants_summary': participants_summary,
        'job': job,
        'slotrange': slotrange,
        'allowed_additional_participants': allowed_additional_participants,
        'job_fully_booked': len(allowed_additional_participants) == 0,
        'job_is_in_past': job.end_time() < datetime.datetime.now()
    })
    return render(request, "job.html", renderdict)


@login_required
def my_depot(request, depot_id):
    """
    Details for a Depot
    """
    depot = get_object_or_404(Depot, id=int(depot_id))

    renderdict = get_menu_dict(request)
    renderdict.update({
        'depot': depot
    })
    return render(request, "depot.html", renderdict)


@login_required
def my_participation(request):
    """
    Details for all areas a loco can participate
    """
    loco = request.user.loco
    my_areas = []
    success = False
    if request.method == 'POST':
        old_areas = set(loco.areas.all())
        new_areas = set(area for area in Taetigkeitsbereich.objects.filter(hidden=False)
                        if request.POST.get("area" + str(area.id)))
        if old_areas != new_areas:
            loco.areas = new_areas
            loco.save()
            for area in new_areas - old_areas:
                send_new_loco_in_taetigkeitsbereich_to_bg(area, loco)

        success = True

    for area in Taetigkeitsbereich.objects.filter(hidden=False):
        if area.hidden:
            continue
        my_areas.append({
            'name': area.name,
            'checked': loco in area.locos.all(),
            'id': area.id,
            'core': area.core,
            'coordinator': area.coordinator
        })

    renderdict = get_menu_dict(request)
    renderdict.update({
        'areas': my_areas,
        'success': success
    })
    return render(request, "participation.html", renderdict)


@login_required
def my_pastjobs(request):
    """
    All past jobs of current user
    """
    loco = request.user.loco

    allebohnen = Boehnli.objects.filter(loco=loco)
    past_bohnen = []

    for bohne in allebohnen:
        if bohne.job.time < datetime.datetime.now():
            past_bohnen.append(bohne)

    renderdict = get_menu_dict(request)
    renderdict.update({
        'bohnen': past_bohnen
    })
    return render(request, "my_pastjobs.html", renderdict)


@permission_required('static_ortoloco.can_send_newsletter')
def send_politoloco(request):
    """
    Send politoloco newsletter
    """
    sent = 0
    if request.method == 'POST':
        emails = set()
        if request.POST.get("allpolitoloco"):
            for loco in Politoloco.objects.all():
                emails.add(loco.email)

        if request.POST.get("allortolocos"):
            for loco in Loco.objects.all():
                emails.add(loco.email)

        if request.POST.get("allsingleemail"):
            emails.add(request.POST.get("singleemail"))

        index = 1
        attachements = []
        while request.FILES.get("image-" + str(index)) is not None:
            attachements.append(request.FILES.get("image-" + str(index)))
            index += 1

        send_politoloco_mail(request.POST.get("subject"), request.POST.get("message"), request.POST.get("textMessage"), emails, request.META["HTTP_HOST"], attachements)
        sent = len(emails)
    renderdict = get_menu_dict(request)
    renderdict.update({
        'politolocos': Politoloco.objects.count(),
        'ortolocos': Loco.objects.count(),
        'sent': sent
    })
    return render(request, 'mail_sender_politoloco.html', renderdict)


@login_required
def my_abo(request):
    """
    Details for an abo of a loco
    """
    renderdict = get_menu_dict(request)

    if request.user.loco.abo != None:
        current_zusatzabos = request.user.loco.abo.extra_abos.all()
        future_zusatzabos = request.user.loco.abo.future_extra_abos.all()
        zusatzabos_changed = (request.user.loco.abo.extra_abos_changed and
                              set(current_zusatzabos) != set(future_zusatzabos))

        if request.user.loco.abo:
            renderdict.update({
                'zusatzabos': current_zusatzabos,
                'future_zusatzabos': future_zusatzabos,
                'zusatzabos_changed': zusatzabos_changed,
                'mitabonnenten': request.user.loco.abo.bezieher_locos().exclude(email=request.user.loco.email),
                'primary': request.user.loco.abo.primary_loco.email == request.user.loco.email,
                'next_extra_abo_date': Abo.next_extra_change_date(),
                'next_size_date': Abo.next_size_change_date()
            })
    renderdict.update({
        'loco': request.user.loco,
        'scheine': request.user.loco.anteilschein_set.count(),
        'scheine_unpaid': request.user.loco.anteilschein_set.filter(paid=False).count(),
    })
    return render(request, "my_abo.html", renderdict)


@primary_loco_of_abo
def my_abo_change(request, abo_id):
    """
    Ein Abo ändern
    """
    month = int(time.strftime("%m"))
    renderdict = get_menu_dict(request)
    renderdict.update({
        'loco': request.user.loco,
        'change_size': month <= 10,
        'next_extra_abo_date': Abo.next_extra_change_date(),
        'next_size_date': Abo.next_size_change_date()
    })
    return render(request, "my_abo_change.html", renderdict)


@primary_loco_of_abo
def my_depot_change(request, abo_id):
    """
    Ein Abo-Depot ändern
    """
    saved = False
    if request.method == "POST":
        request.user.loco.abo.depot = get_object_or_404(Depot, id=int(request.POST.get("depot")))
        request.user.loco.abo.save()
        saved = True
    renderdict = get_menu_dict(request)
    renderdict.update({
        'saved': saved,
        'loco': request.user.loco,
        "depots": Depot.objects.all()
    })
    return render(request, "my_depot_change.html", renderdict)


@primary_loco_of_abo
def my_size_change(request, abo_id):
    """
    Eine Abo-Grösse ändern
    """
    saved = False
    if request.method == "POST" and int(time.strftime("%m")) <=10 and int(request.POST.get("abo")) > 0:
        request.user.loco.abo.future_size = int(request.POST.get("abo"))
        request.user.loco.abo.save()
        saved = True
    renderdict = get_menu_dict(request)
    renderdict.update({
        'saved': saved,
        'size': request.user.loco.abo.future_size
    })
    return render(request, "my_size_change.html", renderdict)


@primary_loco_of_abo
def my_extra_change(request, abo_id):
    """
    Ein Extra-Abos ändern
    """
    saved = False
    if request.method == "POST":
        for extra_abo in ExtraAboType.objects.all():
            if request.POST.get("abo" + str(extra_abo.id)) == str(extra_abo.id):
                request.user.loco.abo.future_extra_abos.add(extra_abo)
                extra_abo.future_extra_abos.add(request.user.loco.abo)
            else:
                request.user.loco.abo.future_extra_abos.remove(extra_abo)
                extra_abo.future_extra_abos.remove(request.user.loco.abo)
            request.user.loco.abo.extra_abos_changed = True
            request.user.loco.abo.save()
            extra_abo.save()

        saved = True

    abos = []
    for abo in ExtraAboType.objects.all():
        if request.user.loco.abo.extra_abos_changed:
            if abo in request.user.loco.abo.future_extra_abos.all():
                abos.append({
                    'id': abo.id,
                    'name': abo.name,
                    'selected': True
                })
            else:
                abos.append({
                    'id': abo.id,
                    'name': abo.name
                })
        else:
            if abo in request.user.loco.abo.extra_abos.all():
                abos.append({
                    'id': abo.id,
                    'name': abo.name,
                    'selected': True
                })
            else:
                abos.append({
                    'id': abo.id,
                    'name': abo.name
                })
    renderdict = get_menu_dict(request)
    renderdict.update({
        'saved': saved,
        'loco': request.user.loco,
        "extras": abos,
        "abo_id": abo_id,
    })
    return render(request, "my_extra_change.html", renderdict)


@login_required
def my_team(request, bereich_id):
    """
    Details for a team
    """

    job_types = JobType.objects.all().filter(bereich=bereich_id)

    jobs = get_current_jobs().filter(typ=job_types)

    renderdict = get_menu_dict(request)
    renderdict.update({
        'team': get_object_or_404(Taetigkeitsbereich, id=int(bereich_id)),
        'jobs': jobs,
    })
    return render(request, "team.html", renderdict)


@login_required
def my_einsaetze(request):
    """
    All jobs to be sorted etc.
    """
    renderdict = get_menu_dict(request)

    jobs = get_current_jobs()
    renderdict.update({
        'jobs': jobs,
        'show_all': True
    })

    return render(request, "jobs.html", renderdict)


@login_required
def my_einsaetze_all(request):
    """
    All jobs to be sorted etc.
    """
    renderdict = get_menu_dict(request)
    jobs = Job.objects.all().order_by("time")
    renderdict.update({
        'jobs': jobs,
    })

    return render(request, "jobs.html", renderdict)


def my_signup(request):
    """
    Become a member of Gartenkooperative
    """
    success = False
    agberror = False
    agbchecked = False
    userexists = False
    if request.method == 'POST':
        agbchecked = request.POST.get("agb") == "on"

        locoform = ProfileLocoForm(request.POST)
        if not agbchecked:
            agberror = True
        else:
            if locoform.is_valid():
                #check if user already exists
                if User.objects.filter(email=locoform.cleaned_data['email']).__len__() > 0:
                    userexists = True
                else:
                    #set all fields of user
                    #email is also username... we do not use it
                    password = password_generator()

                    loco = Loco.objects.create(first_name=locoform.cleaned_data['first_name'], last_name=locoform.cleaned_data['last_name'], email=locoform.cleaned_data['email'])
                    loco.addr_street = locoform.cleaned_data['addr_street']
                    loco.addr_zipcode = locoform.cleaned_data['addr_zipcode']
                    loco.addr_location = locoform.cleaned_data['addr_location']
                    loco.phone = locoform.cleaned_data['phone']
                    loco.mobile_phone = locoform.cleaned_data['mobile_phone']
                    loco.save()

                    loco.user.set_password(password)
                    loco.user.save()

                    #log in to allow him to make changes to the abo
                    loggedin_user = authenticate(username=loco.user.username, password=password)
                    login(request, loggedin_user)
                    success = True
                    return redirect("/my/aboerstellen")
    else:
        locoform = ProfileLocoForm()

    renderdict = {
        'locoform': locoform,
        'success': success,
        'agberror': agberror,
        'agbchecked': agbchecked,
        'userexists': userexists
    }
    return render(request, "signup.html", renderdict)


@login_required
@primary_loco_of_abo
def my_add_loco(request, abo_id):
    scheineerror = False
    scheine = 1
    userexists = False
    if request.method == 'POST':
        locoform = ProfileLocoForm(request.POST)
        if User.objects.filter(email=request.POST.get('email')).__len__() > 0:
            userexists = True
        try:
            # Gartenkooperative organisiert Scheine nicht hier.
            # scheine = int(request.POST.get("anteilscheine"))
            scheine = 100
            scheineerror = scheine < 0
        except TypeError:
            # Gartenkooperative organisiert Scheine nicht hier.
            # scheineerror = True
            scheineerror = False
        except  ValueError:
            # Gartenkooperative organisiert Scheine nicht hier.
            # scheineerror = True
            scheineerror = False
        if locoform.is_valid() and scheineerror is False and userexists is False:
            username = make_username(locoform.cleaned_data['first_name'],
                                     locoform.cleaned_data['last_name'],
                                     locoform.cleaned_data['email'])
            pw = password_generator()
            loco = Loco.objects.create(first_name=locoform.cleaned_data['first_name'], last_name=locoform.cleaned_data['last_name'], email=locoform.cleaned_data['email'])
            loco.first_name = locoform.cleaned_data['first_name']
            loco.last_name = locoform.cleaned_data['last_name']
            loco.email = locoform.cleaned_data['email']
            loco.addr_street = locoform.cleaned_data['addr_street']
            loco.addr_zipcode = locoform.cleaned_data['addr_zipcode']
            loco.addr_location = locoform.cleaned_data['addr_location']
            loco.phone = locoform.cleaned_data['phone']
            loco.mobile_phone = locoform.cleaned_data['mobile_phone']
            loco.confirmed = False
            loco.abo_id = abo_id
            loco.save()

            loco.user.set_password(pw)
            loco.user.save()

            '''
            for num in range(0, scheine):
                anteilschein = Anteilschein(loco=loco, paid=False)
                anteilschein.save()
            '''

            send_been_added_to_abo(loco.email, pw, loco.get_name(), scheine, hashlib.sha1(locoform.cleaned_data['email'] + str(abo_id)).hexdigest(), request.META["HTTP_HOST"])

            loco.save()
            if request.GET.get("return"):
                return redirect(request.GET.get("return"))
            return redirect('/my/aboerstellen')

    else:
        loco = request.user.loco
        initial = {"addr_street": loco.addr_street,
                   "addr_zipcode": loco.addr_zipcode,
                   "addr_location": loco.addr_location,
                   "phone": loco.phone,
        }
        locoform = ProfileLocoForm(initial=initial)
    renderdict = {
        'scheine': scheine,
        'userexists': userexists,
        'scheineerror': scheineerror,
        'locoform': locoform,
        "loco": request.user.loco,
        "depots": Depot.objects.all()
    }
    return render(request, "add_loco.html", renderdict)


@login_required
def my_createabo(request):
    """
    Abo erstellen
    """
    loco = request.user.loco
    scheineerror = False
    if loco.abo is None or loco.abo.size is 1:
        selectedabo = "small"
    elif loco.abo.size is 2:
        selectedabo = "big"
    else:
        selectedabo = "house"

    # Gartenkooperative benützt die Aboscheine dieser Software nicht. Also setzten wir es einfach auf riesig :)
    # loco_scheine = 0
    loco_scheine = 100
    if loco.abo is not None:
        for abo_loco in loco.abo.bezieher_locos().exclude(email=request.user.loco.email):
            loco_scheine += abo_loco.anteilschein_set.all().__len__()

    if request.method == "POST":
        # Gartenkooperative benützt die Aboscheine dieser Software nicht. Also setzten wir es einfach auf riesig :)
        # scheine = int(request.POST.get("scheine"))
        scheine = 100
        selectedabo = request.POST.get("abo")

        scheine += loco_scheine
        if (scheine < 4 and request.POST.get("abo") == "big") or (scheine < 20 and request.POST.get("abo") == "house") or (scheine < 2 and request.POST.get("abo") == "small" ) or (scheine == 0):
            scheineerror = True
        else:
            depot = Depot.objects.all().filter(id=request.POST.get("depot"))[0]
            size = 1
            if request.POST.get("abo") == "house":
                size = 10
            elif request.POST.get("abo") == "big":
                size = 2
            else:
                size = 1
            if loco.abo is None:
                loco.abo = Abo.objects.create(size=size, primary_loco=loco, depot=depot)
            else:
                loco.abo.size = size
                loco.abo.future_size = size
                loco.abo.depot = depot
            loco.abo.save()
            loco.save()

            '''
            # We dont care about anteilsscheine
            if loco.anteilschein_set.count() < int(request.POST.get("scheine")):
              toadd = int(request.POST.get("scheine")) - loco.anteilschein_set.count()
                for num in range(0, toadd):
                    anteilschein = Anteilschein(loco=loco, paid=False)
                    anteilschein.save()
            '''

            if request.POST.get("add_loco"):
                return redirect("/my/abonnent/" + str(loco.abo_id))
            else:
                password = password_generator()

                request.user.set_password(password)
                request.user.save()

                #user did it all => send confirmation mail
                send_welcome_mail(loco.email, password, request.META["HTTP_HOST"], loco)
                send_welcome_mail("info@gartenkooperative.li", "<geheim>", request.META["HTTP_HOST"], loco)

                return redirect("/my/willkommen")

    selected_depot = None
    mit_locos = []
    if request.user.loco.abo is not None:
        selected_depot = request.user.loco.abo.depot
        mit_locos = request.user.loco.abo.bezieher_locos().exclude(email=request.user.loco.email)

    renderdict = {
        'loco_scheine': loco_scheine,
        "loco": request.user.loco,
        "depots": Depot.objects.all(),
        'selected_depot': selected_depot,
        "selected_abo": selectedabo,
        "scheineerror": scheineerror,
        "mit_locos": mit_locos
    }
    return render(request, "createabo.html", renderdict)


@login_required
def my_welcome(request):
    """
    Willkommen
    """

    renderdict = get_menu_dict(request)
    renderdict.update({
        'jobs': get_current_jobs()[:7],
        'teams': Taetigkeitsbereich.objects.filter(hidden=False),
        'no_abo': request.user.loco.abo is None
    })

    return render(request, "welcome.html", renderdict)


def my_confirm(request, hash):
    """
    Confirm from a user that has been added as a Mitabonnent
    """

    for loco in Loco.objects.all():
        if hash == hashlib.sha1(loco.email + str(loco.abo_id)).hexdigest():
            loco.confirmed = True
            loco.save()

    return redirect("/my/home")


@login_required
def my_contact(request):
    """
    Kontaktformular
    """
    fragen = ""
    loco = request.user.loco
        
    if StaticContent.objects.all().filter(name='kontakt_fragen').__len__() > 0:
        fragen = StaticContent.objects.all().filter(name='kontakt_fragen')[0].content + "</br>"

    if request.method == "POST":
        # send mail to bg
        send_contact_form(request.POST.get("subject"), request.POST.get("message"), request.POST.get("recipient"), loco, request.POST.get("copy"))
        # set announce and redirect to home
        renderdict = { 'sent': "1+" }
        return render(request, 'mail_sender_result.html', renderdict)

    renderdict = get_menu_dict(request)
    renderdict.update({
        'usernameAndEmail': loco.first_name + " " + loco.last_name + " <" + loco.email + ">",
        'fragen': fragen
    })
    return render(request, "my_contact.html", renderdict)


@login_required
def my_profile(request):
    success = False
    loco = request.user.loco
    if request.method == 'POST':
        locoform = ProfileLocoForm(request.POST, instance=loco)
        if locoform.is_valid():
            #set all fields of user
            loco.first_name = locoform.cleaned_data['first_name']
            loco.last_name = locoform.cleaned_data['last_name']
            loco.email = locoform.cleaned_data['email']
            loco.addr_street = locoform.cleaned_data['addr_street']
            loco.addr_zipcode = locoform.cleaned_data['addr_zipcode']
            loco.addr_location = locoform.cleaned_data['addr_location']
            loco.phone = locoform.cleaned_data['phone']
            loco.mobile_phone = locoform.cleaned_data['mobile_phone']
            loco.save()

            success = True
    else:
        locoform = ProfileLocoForm(instance=loco)

    renderdict = get_menu_dict(request)
    renderdict.update({
        'locoform': locoform,
        'success': success
    })
    return render(request, "profile.html", renderdict)


@login_required
def my_change_password(request):
    success = False
    if request.method == 'POST':
        form = PasswordForm(request.POST)
        if form.is_valid():
            request.user.set_password(form.cleaned_data['password'])
            request.user.save()
            success = True
    else:
        form = PasswordForm()

    renderdict = get_menu_dict(request)
    renderdict.update({
        'form': form,
        'success': success
    })
    return render(request, 'password.html', renderdict)


def my_new_password(request):
    sent = False
    if request.method == 'POST':
        sent = True
        locos = Loco.objects.filter(email=request.POST.get('username'))
        if len(locos) > 0:
            loco = locos[0]
            pw = password_generator()
            loco.user.set_password(pw)
            loco.user.save()
            send_mail_password_reset(loco.email, pw, request.META["HTTP_HOST"])
        else:
            print "New Password request: No user found by this email: " + request.POST.get('username')

    renderdict = {
        'sent': sent,
        'serverurl': "http://"+request.META["HTTP_HOST"]
    }

    return render(request, 'my_newpassword.html', renderdict)

@staff_member_required
def send_email(request):
    return send_email_intern(request)

@permission_required('my_ortoloco.is_depot_admin')
def send_email_depot(request):
    return send_email_intern(request)

def send_email_intern(request):
    sent = 0
    if request.method != 'POST':
        raise Http404
    emails = set()
    if request.POST.get("allabo") == "on":
        for loco in Loco.objects.exclude(abo=None).filter(abo__active=True):
            emails.add(loco.email)
    if request.POST.get("depotOnly") == "on":
        for d in request.POST.get("depotOnly"):
            if d == "o":
                x = request.POST.get(d)
                for loco in Depot.get(request.POST.get(d)).locos.all:
                    emails.add(loco.email)
                    xxx
    if request.POST.get("allanteilsschein") == "on":
        for loco in Loco.objects.all():
            if loco.anteilschein_set.count() > 0:
                emails.add(loco.email)
    if request.POST.get("all") == "on":
        for loco in Loco.objects.all():
            emails.add(loco.email)
    if request.POST.get("recipients"):
        recipients = re.split(r"\s*,?\s*", request.POST.get("recipients"))
        for recipient in recipients:
            emails.add(recipient)
    if request.POST.get("allsingleemail"):
        emails.add(request.POST.get("singleemail"))

    sender = request.POST.get('senderEmail') or 'info@gartenkooperative.li' 

    index = 1
    attachements = []
    while request.FILES.get("image-" + str(index)) is not None:
        attachements.append(request.FILES.get("image-" + str(index)))
        index += 1

    if len(emails) > 0:
        send_filtered_mail(request.POST.get("subject"), request.POST.get("message"), request.POST.get("textMessage"), emails, request.META["HTTP_HOST"], attachements, sender=sender)
        sent = len(emails)
    renderdict = get_menu_dict(request)
    renderdict.update({
        'sent': sent
    })
    return render(request, 'mail_sender_result.html', renderdict)

def get_locos_for_depots(depots):
    abos = Abo.objects.filter(depot = depots)
    res = []
    for a in abos:
        locos = Loco.objects.filter(abo = a)
        for loco in locos:
            res.append(loco)
    return res

def send_email_to_depot(request):
    sent = 0
    if request.method != 'POST':
        raise Http404
    emails = set()
    depotIds = request.POST.get("depotIds")
    depotIdsAr = depotIds.split(",")
    for d in depotIdsAr:
        depotInput = request.POST.get(d)
        if depotInput == "on":
            locos = get_locos_for_depots(d);
            for loco in locos:
                emails.add(loco.email)
    
    index = 1
    attachements = []
    while request.FILES.get("image-" + str(index)) is not None:
        attachements.append(request.FILES.get("image-" + str(index)))
        index += 1

    if len(emails) > 0:
        send_filtered_mail(request.POST.get("subject"), request.POST.get("message"), request.POST.get("textMessage"), emails, request.META["HTTP_HOST"], attachements)
        sent = len(emails)
    renderdict = get_menu_dict(request)
    renderdict.update({
        'sent': sent
    })
    return render(request, 'mail_sender_result.html', renderdict)


@staff_member_required
def my_mails(request):
    return my_mails_intern(request)

@permission_required('my_ortoloco.is_depot_admin')
def my_mails_depot(request):
    return my_mails_intern(request)

@staff_member_required
def my_mails_job(request):
    renderdict = get_menu_dict(request)
    
    #sender_email = request.user.email
    sender_email = 'garten@gartenkooperative.li'

    renderdict.update({
        'subject_email': request.POST.get("email_subject"),
        'sender_email': sender_email,
        'recipient_type': request.POST.get("recipient_type"),
        'recipient_type_detail': request.POST.get("recipient_type_detail"),
        'recipients': request.POST.get("recipients"),
        'recipients_count': int(request.POST.get("recipients_count") or 0),
    })
    return render(request, 'mail_sender.html', renderdict)

def my_mails_intern(request):
    """
    Method to send an email from the primary gartenkooperative address.
    """
    renderdict = get_menu_dict(request)

    #sender_email = request.user.email
    sender_email = 'info@gartenkooperative.li'

    renderdict.update({
        'subject_email': request.POST.get("email_subject"),
        'sender_email': sender_email,
        'recipient_type': request.POST.get("recipient_type"),
        'recipient_type_detail': request.POST.get("recipient_type_detail"),
        'recipients': request.POST.get("recipients"),
        'recipients_count': int(request.POST.get("recipients_count") or 0),
        'filter_value': request.POST.get("filter_value")
    })
    return render(request, 'mail_sender.html', renderdict)

def current_year_boehlis():
    now = datetime.date.today()
    return Boehnli.objects.filter(job__time__year=now.year, job__time__lt=now)


def current_year_boehnlis_per_loco():
    boehnlis = current_year_boehlis()
    boehnlis_per_loco = defaultdict(int)
    for boehnli in boehnlis:
        boehnlis_per_loco[boehnli.loco] += 1
    return boehnlis_per_loco

def current_year_kernbereich_boehnlis_per_loco():
    boehnlis = current_year_boehlis()
    boehnlis_per_loco = defaultdict(int)
    for boehnli in boehnlis:
        if boehnli.is_in_kernbereich():
            boehnlis_per_loco[boehnli.loco] += 1
    return boehnlis_per_loco


@staff_member_required
def my_filters(request):
    locos = Loco.objects.all()
    boehnlis = current_year_boehnlis_per_loco()
    boehnlis_kernbereich = current_year_kernbereich_boehnlis_per_loco()
    for loco in locos:
        loco.boehnlis = boehnlis[loco]
        loco.boehnlis_kernbereich = boehnlis_kernbereich[loco]

    renderdict = get_menu_dict(request)
    renderdict.update({
        'locos': locos
    })
    return render(request, 'filters.html', renderdict)


@permission_required('my_ortoloco.is_depot_admin')
def my_filters_depot(request):
    depots = Depot.objects.filter(contact=request.user)
    locos = get_locos_for_depots(depots)
    boehnlis = current_year_boehnlis_per_loco()
    boehnlis_kernbereich = current_year_kernbereich_boehnlis_per_loco()
    for loco in locos:
        loco.boehnlis = boehnlis[loco]
        loco.boehnlis_kernbereich = boehnlis_kernbereich[loco]

    renderdict = get_menu_dict(request)
    renderdict.update({
        'locos': locos
    })
    return render(request, 'filters.html', renderdict)


@staff_member_required
def my_abos(request):
    boehnli_map = current_year_boehnlis_per_loco()
    boehnlis_kernbereich_map = current_year_kernbereich_boehnlis_per_loco()
    abos = []
    for abo in Abo.objects.filter():
        boehnlis = 0
        boehnlis_kernbereich = 0
        for loco in abo.bezieher_locos():
            boehnlis += boehnli_map[loco]
            boehnlis_kernbereich += boehnlis_kernbereich_map[loco]

        abos.append({
            'abo': abo,
            'text': get_status_bean_text(100 / (abo.size * 10) * boehnlis if abo.size > 0 else 0),
            'boehnlis': boehnlis,
            'boehnlis_kernbereich': boehnlis_kernbereich,
            'icon': helpers.get_status_bean(100 / (abo.size * 10) * boehnlis if abo.size > 0 else 0)
        })

    renderdict = get_menu_dict(request)
    renderdict.update({
        'abos': abos
    })

    return render(request, 'abos.html', renderdict)


@permission_required('my_ortoloco.is_depot_admin')
def my_abos_depot(request):
    boehnli_map = current_year_boehnlis_per_loco()
    boehnlis_kernbereich_map = current_year_kernbereich_boehnlis_per_loco()
    abos = []
    depots = Depot.objects.filter(contact=request.user)
    for abo in Abo.objects.filter(depot = depots):
        boehnlis = 0
        boehnlis_kernbereich = 0
        for loco in abo.bezieher_locos():
            boehnlis += boehnli_map[loco]
            boehnlis_kernbereich += boehnlis_kernbereich_map[loco]

        abos.append({
            'abo': abo,
            'text': get_status_bean_text(100 / (abo.size * 10) * boehnlis if abo.size > 0 else 0),
            'boehnlis': boehnlis,
            'boehnlis_kernbereich': boehnlis_kernbereich,
            'icon': helpers.get_status_bean(100 / (abo.size * 10) * boehnlis if abo.size > 0 else 0)
        })

    renderdict = get_menu_dict(request)
    renderdict.update({
        'abos': abos
    })

    return render(request, 'abos.html', renderdict)


@staff_member_required
def my_depotlisten(request):
    return alldepots_list(request, "")


def logout_view(request):
    auth.logout(request)
    # Redirect to a success page.
    return HttpResponseRedirect("/")


def alldepots_list(request, name):
    """
    Printable list of all depots to check on get gemüse
    """
    if name == "":
        depots = Depot.objects.all().order_by("code")
    else:
        depots = [get_object_or_404(Depot, code__iexact=name)]

    overview = {
        'Mittwoch': {
            'small_abo': 0,
            'big_abo': 0,
            'entities': 0,
            'egg6': 0,
            'egg12': 0,
            'egg18': 0,
            'cheesefull': 0,
            'cheesehalf': 0,
            'cheesequarter': 0,
            'bigobst': 0,
            'smallobst': 0
        },
        'Donnerstag': {
            'small_abo': 0,
            'big_abo': 0,
            'entities': 0,
            'egg4': 0,
            'egg6': 0,
            'cheesefull': 0,
            'cheesehalf': 0,
            'cheesequarter': 0,
            'bigobst': 0,
            'smallobst': 0
        },
        'all': {
            'small_abo': 0,
            'big_abo': 0,
            'entities': 0,
            'egg6': 0,
            'egg12': 0,
            'egg18': 0,
            'cheesefull': 0,
            'cheesehalf': 0,
            'cheesequarter': 0,
            'bigobst': 0,
            'smallobst': 0
        }
    }

    for depot in depots:
        row = overview.get(depot.get_weekday_display())
        all = overview.get('all')
        row['small_abo'] += depot.small_abos()
        row['big_abo'] += depot.big_abos()
        row['entities'] += 2 * depot.big_abos() + depot.small_abos()
        row['egg6'] += depot.sechs_eier()
        row['egg12'] += depot.zwoelf_eier()
        row['egg18'] += depot.achtzehn_eier()
        row['cheesefull'] += depot.kaese_ganz()
        row['cheesehalf'] += depot.kaese_halb()
        row['cheesequarter'] += depot.kaese_viertel()
        row['bigobst'] += depot.big_obst()
        row['smallobst'] += depot.small_obst()
        all['small_abo'] += depot.small_abos()
        all['big_abo'] += depot.big_abos()
        all['entities'] += 2 * depot.big_abos() + depot.small_abos()
        all['egg6'] += depot.sechs_eier()
        all['egg12'] += depot.zwoelf_eier()
        all['egg18'] += depot.achtzehn_eier()
        all['cheesefull'] += depot.kaese_ganz()
        all['cheesehalf'] += depot.kaese_halb()
        all['cheesequarter'] += depot.kaese_viertel()
        all['bigobst'] += depot.big_obst()
        all['smallobst'] += depot.small_obst()

    renderdict = {
        "overview": overview,
        "depots": depots,
        "datum": datetime.datetime.now()
    }

    return render_to_pdf(request, "exports/all_depots.html", renderdict, 'Depotlisten')


def my_createlocoforsuperuserifnotexist(request):
    """
    just a helper to create a loco for superuser
    """
    if request.user.is_superuser:
        signals.post_save.disconnect(Loco.create, sender=Loco)
        loco = Loco.objects.create(user=request.user, first_name="super", last_name="duper", email=request.user.email, addr_street="superstreet", addr_zipcode="8000",
                                   addr_location="SuperCity", phone="012345678")
        loco.save()
        request.user.loco = loco
        request.user.save()
        signals.post_save.connect(Loco.create, sender=Loco)


    # we do just nothing if its not a superuser or he has already a loco
    return redirect("/my/home")


@staff_member_required
def my_future(request):
    renderdict = get_menu_dict(request)

    small_abos = 0
    big_abos = 0
    house_abos = 0
    small_abos_future = 0
    big_abos_future = 0
    house_abos_future = 0

    extra_abos = dict({})
    for extra_abo in ExtraAboType.objects.all():
        extra_abos[extra_abo.id] = {
            'name': extra_abo.name,
            'future': 0,
            'now': str(extra_abo.extra_abos.count())
        }

    for abo in Abo.objects.all():
        small_abos += abo.size % 2
        big_abos += int(abo.size % 10 / 2)
        house_abos += int(abo.size / 10)
        small_abos_future += abo.future_size % 2
        big_abos_future += int(abo.future_size % 10 / 2)
        house_abos_future += int(abo.future_size / 10)

        if abo.extra_abos_changed:
            for users_abo in abo.future_extra_abos.all():
                extra_abos[users_abo.id]['future'] += 1
        else:
            for users_abo in abo.extra_abos.all():
                extra_abos[users_abo.id]['future'] += 1

    month = int(time.strftime("%m"))
    day = int(time.strftime("%d"))

    renderdict.update({
        'changed': request.GET.get("changed"),
        'big_abos': big_abos,
        'house_abos': house_abos,
        'small_abos': small_abos,
        'big_abos_future': big_abos_future,
        'house_abos_future': house_abos_future,
        'small_abos_future': small_abos_future,
        'extras': extra_abos.itervalues(),
        # 'abo_change_enabled': month is 12 or (month is 1 and day <= 6)
        'abo_change_enabled': True
    })
    return render(request, 'future.html', renderdict)


@staff_member_required
def my_switch_extras(request):
    renderdict = get_menu_dict(request)

    for abo in Abo.objects.all():
        if abo.extra_abos_changed:
            abo.extra_abos = []
            for extra in abo.future_extra_abos.all():
                abo.extra_abos.add(extra)

            abo.extra_abos_changed = False
            abo.save()


    renderdict.update({
    })

    return redirect('/my/zukunft?changed=true')

@staff_member_required
def my_switch_abos(request):
    renderdict = get_menu_dict(request)

    for abo in Abo.objects.all():
        if abo.size is not abo.future_size:
            if abo.future_size is 0:
                abo.active = False
            if abo.size is 0:
                abo.active = True
            abo.size = abo.future_size
            abo.save()


    renderdict.update({
    })

    return redirect('/my/zukunft?changed=true')


@staff_member_required
def my_startmigration(request):
    f = StringIO()
    with Swapstd(f):
        call_command('clean_db')
        call_command('import_old_db', request.GET.get("username"), request.GET.get("password"))
    return HttpResponse(f.getvalue(), content_type="text/plain")


@staff_member_required
def migrate_apps(request):
    f = StringIO()
    with Swapstd(f):
        call_command('migrate', 'my_ortoloco')
        call_command('migrate', 'static_ortoloco')
    return HttpResponse(f.getvalue(), content_type="text/plain")


@staff_member_required
def pip_install(request):
    command = "pip install -r requirements.txt"
    res = run_in_shell(request, command)
    return res


def mini_migrate_future_zusatzabos(request):
    new_abo_future_extra = []
    Throughclass = Abo.future_extra_abos.through

    abos = Abo.objects.filter(extra_abos_changed=False)
    for abo in abos:
        for extra in abo.extra_abos.all():
            new_abo_future_extra.append(Throughclass(extraabotype=extra, abo=abo))

    Throughclass.objects.bulk_create(new_abo_future_extra)
    abos.update(extra_abos_changed=True)
    return HttpResponse("Done!")


def test_filters(request):
    lst = Filter.get_all()
    res = []
    for name in Filter.get_names():
        res.append("<br><br>%s:" % name)
        tmp = Filter.execute([name], "OR")
        data = Filter.format_data(tmp, unicode)
        res.extend(data)
    return HttpResponse("<br>".join(res))


def test_filters_post(request):
    # TODO: extract filter params from post request
    # the full list of filters is obtained by Filter.get_names()
    filters = ["Zusatzabo Eier", "Depot GZ Oerlikon"]
    op = "AND"
    res = ["Eier AND Oerlikon:<br>"]
    locos = Filter.execute(filters, op)
    data = Filter.format_data(locos, lambda loco: "%s! (email: %s)" % (loco, loco.email))
    res.extend(data)
    return HttpResponse("<br>".join(res))




