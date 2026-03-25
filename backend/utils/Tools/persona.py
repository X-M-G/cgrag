from django.utils import timezone

def record_user_activity(user):
    """
    记录用户当天活跃事实
    不计算 frequency
    """
    persona = user.persona
    today = timezone.now().date()

    persona.total_questions += 1

    if persona.last_active_date != today:
        persona.active_days += 1
        persona.last_active_date = today

    persona.save(update_fields=[
        'total_questions',
        'active_days',
        'last_active_date',
        'updated_at'
    ])
