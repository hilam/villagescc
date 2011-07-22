from django.shortcuts import get_object_or_404, redirect
from django.http import HttpResponseRedirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from cc.general.util import render
from cc.profile.forms import RegistrationForm, ProfileForm, ContactForm
from cc.profile.models import Profile
from cc.feed.models import FeedItem
from cc.post.models import Post

MESSAGES = {
    'profile_saved': "Profile saved.",
    'contact_sent': "Message sent.",
}

@render()
def register(request):
    if 'done' in request.GET:
        return {}, 'register_done.html'
    
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect('?done=1')
    else:
        form = RegistrationForm()
    return locals()

@login_required
@render()
def edit_profile(request):
    profile = request.profile
    if request.method == 'POST':
        form = ProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.info(request, MESSAGES['profile_saved'])
            return HttpResponseRedirect(profile.get_absolute_url())
    else:
        form = ProfileForm(instance=profile)
    return locals()

@render()
def profiles(request):
    profiles = FeedItem.objects.get_feed(
        request.profile, radius=None, item_type_filter=Profile)
    return locals()

@render()
def profile(request, username):
    profile = get_object_or_404(Profile, user__username=username)
    if request.profile:
        my_endorsement = request.profile.endorsement_for(profile)
    return locals()
        
@render()
def profile_posts(request, username):
    profile = get_object_or_404(Profile, user__username=username)
    posts = profile.posts.order_by('-date')
    return locals()

@render()
def profile_endorsements(request, username):
    profile = get_object_or_404(Profile, user__username=username)
    endorsements = profile.endorsements_received.order_by('-updated')
    return locals()

@render()
def contact(request, username):
    profile = get_object_or_404(Profile, user__username=username)
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            form.send(sender=request.profile, recipient=profile)
            messages.info(request, MESSAGES['contact_sent'])
            return redirect(profile, (username,))
    else:
        form = ContactForm()
    return locals()
