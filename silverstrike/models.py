import uuid

from datetime import date, datetime, timedelta

from dateutil.relativedelta import relativedelta

from django.db import models
from django.urls import reverse
from django.utils.translation import ugettext as _


class Account(models.Model):
    PERSONAL = 1
    REVENUE = 2
    EXPENSE = 3
    SYSTEM = 4
    ACCOUNT_TYPES = (
        (PERSONAL, _('Personal')),
        (REVENUE, _('Revenue')),
        (EXPENSE, _('Expense')),
        (SYSTEM, _('System')),
    )

    name = models.CharField(max_length=64)
    account_type = models.IntegerField(choices=ACCOUNT_TYPES, default=PERSONAL)
    active = models.BooleanField(default=True)
    last_modified = models.DateTimeField(auto_now=True)
    show_on_dashboard = models.BooleanField(default=False)

    class Meta:
        ordering = ['-show_on_dashboard', 'name']

    def __str__(self):
        return self.name

    def account_type_str(self):
        return Account.ACCOUNT_TYPES[self.account_type - 1][1]

    @property
    def is_personal(self):
        return self.account_type == Account.PERSONAL

    @property
    def transaction_num(self):
        return Split.objects.filter(account=self).count()

    @property
    def balance(self):
        return Split.objects.filter(account=self).aggregate(
            models.Sum('amount'))['amount__sum'] or 0

    def balance_on(self, date):
        return Split.objects.filter(account=self, journal__date__lte=date).aggregate(
            models.Sum('amount'))['amount__sum'] or 0

    def get_absolute_url(self):
        return reverse('account_detail',
                       kwargs={'pk': self.pk, 'month': datetime.strftime(date.today(), '%Y%m')})

    def get_data_points(self, dstart=date.today() - timedelta(days=365),
                        dend=date.today(), steps=30):
        step = (dend - dstart) / steps
        if step < timedelta(days=1):
            step = timedelta(days=1)
            steps = int((dend - dstart) / step)
        data_points = []
        balance = self.balance_on(dstart)
        transactions = list(Split.objects.prefetch_related('journal').filter(
            account_id=self.pk, journal__date__gt=dstart,
            journal__date__lte=dend).order_by('-journal__date'))
        for i in range(steps):
            while len(transactions) > 0 and transactions[-1].journal.date <= dstart.date():
                t = transactions.pop()
                balance += t.amount
            data_points.append((dstart, balance))
            dstart += step
        for t in transactions:
            balance += t.amount
        data_points.append((dend, balance))
        return data_points

    def set_initial_balance(self, amount):
        system = Account.objects.get(account_type=Account.SYSTEM)
        journal = Journal.objects.create(title=_('Initial Balance'),
                                         transaction_type=Journal.SYSTEM)
        Split.objects.create(journal=journal, amount=-amount,
                             account=system, opposing_account=self)
        Split.objects.create(journal=journal, amount=amount,
                             account=self, opposing_account=system)


class SplitManager(models.Manager):
    def transactions(self):
        queryset = self.get_queryset().filter(account__account_type=Account.PERSONAL)
        return queryset.exclude(journal__transaction_type=Journal.TRANSFER, amount__gt=0)

    def income(self, month=date.today(), account=None):
        from .lib import last_day_of_month

        first = month.replace(day=1)
        last = last_day_of_month(first)
        queryset = self.get_queryset().filter(account__account_type=Account.PERSONAL,
                                              opposing_account__account_type=Account.REVENUE)
        queryset = queryset.filter(date__gte=first, date__lte=last)
        if account:
            queryset = queryset.filter(account=account)
        return queryset.aggregate(models.Sum('amount'))['amount__sum'] or 0

    def expenses(self, month=date.today(), account=None):
        from .lib import last_day_of_month

        first = month.replace(day=1)
        last = last_day_of_month(first)
        queryset = self.get_queryset().filter(account__account_type=Account.EXPENSE,
                                              opposing_account__account_type=Account.PERSONAL)
        queryset = queryset.filter(date__gte=first, date__lte=last)
        if account:
            queryset = queryset.filter(opposing_account=account)
        return queryset.aggregate(models.Sum('amount'))['amount__sum'] or 0


class Journal(models.Model):
    DEPOSIT = 1
    WITHDRAW = 2
    TRANSFER = 3
    SYSTEM = 4
    TRANSACTION_TYPES = (
        (DEPOSIT, 'Deposit'),
        (WITHDRAW, 'Withdrawl'),
        (TRANSFER, 'Transfer'),
        (SYSTEM, 'Reconcile'),
    )

    class Meta:
        ordering = ['-date', 'title']

    title = models.CharField(max_length=64)
    date = models.DateField(default=date.today)
    notes = models.TextField(blank=True, null=True)
    transaction_type = models.IntegerField(choices=TRANSACTION_TYPES)
    recurrence = models.ForeignKey('RecurringTransaction', related_name='recurrences',
                                   blank=True, null=True)

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('transaction_detail', args=[self.pk])

    def get_transaction_type_str(self):
        for i, name in self.TRANSACTION_TYPES:
            if i == self.transaction_type:
                return name
        return ''

    @property
    def amount(self):
        return self.splits.filter(account__account_type=Account.PERSONAL).aggregate(
            models.Sum('amount'))['amount__sum'] or 0

    @property
    def is_split(self):
        return len(self.splits.all()) > 2


class Split(models.Model):
    account = models.ForeignKey(Account, models.CASCADE, related_name='incoming_transactions')
    opposing_account = models.ForeignKey(Account, models.CASCADE,
                                         related_name='outgoing_transactions')
    description = models.CharField(max_length=64)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField(default=date.today)
    category = models.ForeignKey('Category', blank=True, null=True)
    journal = models.ForeignKey(Journal, models.CASCADE, related_name='splits',
                                blank=True, null=True)

    objects = SplitManager()

    class Meta:
        ordering = ['-date', 'journal', 'description']

    def __str__(self):
        return self.description

    @property
    def is_transfer(self):
        return self.journal.transaction_type == Journal.TRANSFER

    @property
    def is_withdraw(self):
        return self.journal.transaction_type == Journal.WITHDRAW

    @property
    def is_deposit(self):
        return self.journal.transaction_type == Journal.DEPOSIT

    @property
    def is_system(self):
        return self.journal.transaction_type == Journal.SYSTEM

    def get_absolute_url(self):
        return self.journal.get_absolute_url()


class Category(models.Model):
    name = models.CharField(max_length=64)
    last_modified = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.name

    @property
    def money_spent(self):
        return abs(Split.objects.filter(
                category=self, account__account_type=Account.PERSONAL,
                journal__transaction_type=Journal.WITHDRAW).aggregate(
            models.Sum('amount'))['amount__sum'] or 0)


class ImportFile(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to='imports')


class ImportConfiguration(models.Model):
    DO_NOT_USE = 0
    SOURCE_ACCOUNT = 1
    DESTINATION_ACCOUNT = 2
    AMOUNT = 3
    DATE = 4
    NOTES = 5
    CATEGORY = 6
    TITLE = 7

    FIELD_TYPES = (
        (DO_NOT_USE, _('Do not use')),
        (SOURCE_ACCOUNT, _('Source Account')),
        (DESTINATION_ACCOUNT, _('Destination Account')),
        (AMOUNT, _('Amount')),
        (DATE, _('Date')),
        (NOTES, _('Notes')),
        (CATEGORY, _('Category')),
        )

    name = models.CharField(max_length=64)
    headers = models.BooleanField(help_text=_('First line contains headers'))
    default_account = models.ForeignKey(Account,
                                        limit_choices_to={'account_type': Account.PERSONAL},
                                        null=True, blank=True)
    config = models.TextField()

    def __str__(self):
        return self.name


class RecurringTransactionManager(models.Manager):
    def due_in_month(self, month=None):
        from .lib import last_day_of_month
        if not month:
            month = date.today()
        month = last_day_of_month(month)
        return self.get_queryset().filter(date__lte=month)


class RecurringTransaction(models.Model):
    WEEKLY = 1
    MONTHLY = 2
    YEARLY = 3
    RECCURENCE_OPTIONS = (
        (WEEKLY, _('Weekly')),
        (MONTHLY, _('Monthly')),
        (YEARLY, _('Yearly')))

    class Meta:
        ordering = ['date']

    objects = RecurringTransactionManager()

    title = models.CharField(max_length=64)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField()
    src = models.ForeignKey(Account)
    dst = models.ForeignKey(Account, related_name='opposing_recurring_transactions')
    recurrence = models.IntegerField(choices=RECCURENCE_OPTIONS)
    transaction_type = models.IntegerField(choices=Journal.TRANSACTION_TYPES[:3])

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('recurrence_detail', args=[self.pk])

    @property
    def is_due(self):
        return date.today() >= self.date

    def update_date(self):
        if self.recurrence == self.WEEKLY:
            self.date += timedelta(days=7)
        elif self.recurrence == self.MONTHLY:
            self.date += relativedelta(months=+1)
        else:
            self.date += relativedelta(years=+1)

    @property
    def get_recurrence(self):
        for r, name in self.RECCURENCE_OPTIONS:
            if r == self.recurrence:
                return name
        return ''

    @classmethod
    def outstanding_transaction_sum(cls):
        from .lib import last_day_of_month
        outstanding = 0
        dend = last_day_of_month(date.today())
        transactions = cls.objects.due_in_month().exclude(
            transaction_type=Journal.TRANSFER)
        for t in transactions:
            while t.date <= dend:
                if t.transaction_type == Journal.WITHDRAW:
                    outstanding -= t.amount
                else:
                    outstanding += t.amount
                t.update_date()
        return outstanding