import datetime

from django.db import models
from django.http import HttpResponseNotAllowed, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404

from .models import Account, RecurringTransaction, Split


def get_accounts(request, account_type):
    accounts = Account.objects.exclude(account_type=Account.SYSTEM)
    if account_type != 'all':
        account_type = getattr(Account, account_type)
        accounts = accounts.filter(account_type=account_type)

    return JsonResponse(list(accounts.values_list('name', flat=True)), safe=False)


def get_accounts_balance(request, dstart, dend):
    dstart = datetime.datetime.strptime(dstart, '%Y-%m-%d')
    dend = datetime.datetime.strptime(dend, '%Y-%m-%d')
    dataset = []
    for account in Account.objects.filter(account_type=Account.PERSONAL, show_on_dashboard=True):
        data = list(zip(*account.get_data_points(dstart, dend)))
        dataset.append({'name': account.name, 'data': data[1]})
    if dataset:
        labels = [datetime.datetime.strftime(x, '%d %b %Y') for x in data[0]]
    else:
        labels = []
    return JsonResponse({'labels': labels, 'dataset': dataset})


def get_balances(request, dstart, dend):
    dstart = datetime.datetime.strptime(dstart, '%Y-%m-%d')
    dend = datetime.datetime.strptime(dend, '%Y-%m-%d')
    dataset = []
    balance = Split.objects.filter(account__account_type=Account.PERSONAL,
                                   date__lte=dstart).aggregate(
            models.Sum('amount'))['amount__sum'] or 0
    for i in range(30):
        pass

def skip_recurrence(request, pk):
    if request.method == 'GET':
        return HttpResponseNotAllowed(['POST'])
    recurrence = get_object_or_404(RecurringTransaction, pk=pk)
    recurrence.update_date()
    recurrence.save()
    return HttpResponseRedirect(request.GET['next'])