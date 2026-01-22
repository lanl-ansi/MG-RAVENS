import torch

def train_epoch(model, loader, loss_fn, optimizer, device):
    model.train()
    total_loss = 0.0
    for data in loader:
        data = data.to(device)

        optimizer.zero_grad()
        pred   = model(data)              
        # target = data.y["edge_attr"]  #NOTE: changed for new loss function
        target = data         
        loss   = loss_fn(pred, target)


        loss.backward()
        optimizer.step()

        total_loss += loss.item() * data.num_graphs
    return total_loss / len(loader.dataset)

def validate(model, loader, loss_fn, device):
    model.eval()
    total_loss = 0.0
    with torch.no_grad():
        for data in loader:
            data = data.to(device)
            pred   = model(data)
            # target = data.y["edge_attr"] #NOTE: changed for new loss function
            target = data
            loss   = loss_fn(pred, target)
            total_loss += loss.item() * data.num_graphs
    return total_loss / len(loader.dataset)