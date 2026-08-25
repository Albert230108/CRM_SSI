from app.models.gmail_integration import GmailAccount
import app.api.users as users_api


def test_default_accounts_round_trip(non_admin_client, db_session, monkeypatch):
    gmail = GmailAccount(email_address='default-gmail@example.com', is_active=True)
    db_session.add(gmail)
    db_session.commit()
    db_session.refresh(gmail)

    monkeypatch.setattr(
        users_api,
        'list_whatsapp_accounts',
        lambda: [
            {
                'external_account_id': 'whatsapp-default',
                'provider': 'whatsapp-service',
                'label': 'Default WhatsApp',
            }
        ],
    )

    response = non_admin_client.patch(
        '/api/users/me/default-accounts',
        json={
            'default_gmail_account_id': gmail.id,
            'default_whatsapp_account_id': 'whatsapp-default',
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['default_gmail_account_id'] == gmail.id
    assert body['default_whatsapp_account_id'] == 'whatsapp-default'

    me_response = non_admin_client.get('/api/auth/me')
    assert me_response.status_code == 200
    me = me_response.json()
    assert me['default_gmail_account_id'] == gmail.id
    assert me['default_whatsapp_account_id'] == 'whatsapp-default'
